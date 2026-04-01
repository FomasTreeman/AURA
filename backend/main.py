"""
AURA backend – FastAPI application.
Exposes:
  POST /ingest  – ingest a directory of PDFs or uploaded files
  POST /query   – ask a question, receive a streamed JSON-lines response
  GET  /health  – liveness check (includes Ollama status)
  GET  /stats   – collection document count
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.config import (
    INGEST_DIR,
    P2P_BOOTSTRAP,
    P2P_HOST,
    P2P_KEY_DIR,
    P2P_MDNS_ENABLED,
    P2P_PORT,
)
from backend.ingestion.pipeline import ingest_directory, ingest_file
from backend.rag.generator import check_ollama, stream_answer
from backend.database.chroma import get_collection
from backend.network.libp2p_adapter import AuraP2PAdapter
from backend.network.metrics import METRICS
from backend.network.peer import PeerIdentity
from backend.network.rendezvous import BootstrapDiscovery, MDNSDiscovery
from backend.utils.logging import get_logger

log = get_logger(__name__)


# ── Startup/shutdown ──────────────────────────────────────────────────────────

# Module-level P2P singletons (set during lifespan)
_adapter: AuraP2PAdapter | None = None
_mdns: MDNSDiscovery | None = None
_bootstrap: BootstrapDiscovery | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup checks, then start the P2P adapter."""
    global _adapter, _mdns, _bootstrap

    log.info("AURA node starting…")

    # ── Ollama check (non-fatal) ───────────────────────────────────────────────
    try:
        check_ollama()
    except RuntimeError as exc:
        log.error("Ollama startup check failed: %s", exc)

    # ── P2P Network ───────────────────────────────────────────────────────────
    identity = PeerIdentity.load_or_create(P2P_KEY_DIR)
    _adapter = AuraP2PAdapter(identity)
    try:
        await _adapter.start(host=P2P_HOST, port=P2P_PORT)
        log.info("P2P node started: peer_id=%s", identity.peer_id[:24])
    except Exception as exc:
        log.error("P2P adapter failed to start: %s", exc)
        _adapter = None

    if _adapter is not None:
        # mDNS LAN discovery
        if P2P_MDNS_ENABLED:
            _mdns = MDNSDiscovery(identity, _adapter, P2P_PORT)
            try:
                await _mdns.start()
            except Exception as exc:
                log.warning("mDNS failed to start: %s", exc)
                _mdns = None

        # Bootstrap peers
        _bootstrap = BootstrapDiscovery(_adapter, P2P_BOOTSTRAP)
        await _bootstrap.start()

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    log.info("AURA node shutting down…")
    if _bootstrap:
        await _bootstrap.stop()
    if _mdns:
        await _mdns.stop()
    if _adapter:
        await _adapter.stop()
    log.info("AURA node shutdown complete.")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="AURA – Sovereign Local Node",
    description="Offline RAG: ingest PDFs, query with a local LLM.",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Request/response models ───────────────────────────────────────────────────

class IngestRequest(BaseModel):
    """Request body for directory-based ingestion."""
    directory: str | None = None  # defaults to INGEST_DIR env var


class QueryRequest(BaseModel):
    """Request body for a RAG query."""
    question: str


class IngestResponse(BaseModel):
    """Summary of an ingestion run."""
    files_processed: int
    total_chunks: int
    results: list[dict]


class StatsResponse(BaseModel):
    """Basic stats about the vector store."""
    collection: str
    document_count: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    """
    Liveness check.
    Returns Ollama status and collection size.
    """
    ollama_ok = False
    ollama_error = None
    try:
        check_ollama()
        ollama_ok = True
    except RuntimeError as exc:
        ollama_error = str(exc)

    collection = get_collection()
    return {
        "status": "ok",
        "ollama": {"running": ollama_ok, "error": ollama_error},
        "vector_store": {"count": collection.count()},
    }


@app.get("/stats", response_model=StatsResponse)
async def stats() -> StatsResponse:
    """Return basic stats about the current vector store."""
    collection = get_collection()
    return StatsResponse(
        collection=collection.name,
        document_count=collection.count(),
    )


@app.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    """
    Ingest all PDF files in a directory into the AURA vector store.

    The directory defaults to the INGEST_DIR environment variable if not supplied.
    """
    directory = Path(request.directory) if request.directory else INGEST_DIR

    if not directory.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Directory not found or not a directory: {directory}",
        )

    try:
        results = ingest_directory(directory)
    except Exception as exc:
        log.error("Ingestion error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    total_chunks = sum(r.get("chunks_added", 0) for r in results)  # type: ignore[arg-type]
    return IngestResponse(
        files_processed=len(results),
        total_chunks=total_chunks,
        results=results,
    )


@app.post("/ingest/upload")
async def ingest_upload(files: list[UploadFile] = File(...)):
    """
    Accept multipart PDF uploads, write them to INGEST_DIR, and ingest them.
    """
    import tempfile, shutil

    INGEST_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for upload in files:
        if not upload.filename or not upload.filename.lower().endswith(".pdf"):
            results.append({"file": upload.filename, "error": "Not a PDF", "chunks_added": 0})
            continue
        dest = INGEST_DIR / upload.filename
        with open(dest, "wb") as fh:
            shutil.copyfileobj(upload.file, fh)
        try:
            result = ingest_file(dest)
            results.append(result)
        except Exception as exc:
            log.error("Upload ingest error for '%s': %s", upload.filename, exc)
            results.append({"file": upload.filename, "error": str(exc), "chunks_added": 0})

    total_chunks = sum(r.get("chunks_added", 0) for r in results)  # type: ignore[arg-type]
    return {"files_processed": len(results), "total_chunks": total_chunks, "results": results}


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus-compatible metrics endpoint."""
    return Response(
        content=METRICS.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/network/status")
async def network_status() -> dict:
    """Return the current P2P network status for this node."""
    if _adapter is None:
        return {"running": False, "peer_id": None, "peers": 0, "multiaddr": None}
    return {
        "running": True,
        "peer_id": _adapter.peer_id,
        "multiaddr": _adapter.multiaddr,
        "peers": len(_adapter.get_peers()),
        "mdns_enabled": P2P_MDNS_ENABLED,
    }


@app.get("/network/peers")
async def network_peers() -> dict:
    """List all currently connected P2P peers."""
    if _adapter is None:
        return {"peers": []}
    peers = [
        {
            "peer_id": p.peer_id,
            "multiaddrs": p.multiaddrs,
        }
        for p in _adapter.get_peers()
    ]
    return {"count": len(peers), "peers": peers}


@app.post("/network/dial")
async def network_dial(body: dict) -> dict:
    """
    Manually dial a peer by multiaddr.
    Body: {"multiaddr": "/ip4/1.2.3.4/tcp/9000/p2p/Qm..."}
    """
    if _adapter is None:
        raise HTTPException(status_code=503, detail="P2P adapter not running.")
    multiaddr = body.get("multiaddr")
    if not multiaddr:
        raise HTTPException(status_code=400, detail="multiaddr is required.")
    peer = await _adapter.dial(multiaddr)
    if peer is None:
        raise HTTPException(status_code=502, detail=f"Failed to connect to {multiaddr}")
    return {"connected": True, "peer_id": peer.peer_id}


@app.post("/query")
async def query(request: QueryRequest) -> StreamingResponse:
    """
    Ask a question against ingested documents.

    Returns a streaming JSON-lines response.
    Each line is one of:
      {"token": "..."}              – intermediate LLM token
      {"done": true, "sources": []} – final message with source citations
      {"error": "..."}              – error message
    """
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    return StreamingResponse(
        stream_answer(request.question),
        media_type="application/x-ndjson",
    )

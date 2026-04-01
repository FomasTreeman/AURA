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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.config import INGEST_DIR
from backend.ingestion.pipeline import ingest_directory, ingest_file
from backend.rag.generator import check_ollama, stream_answer
from backend.database.chroma import get_collection
from backend.utils.logging import get_logger

log = get_logger(__name__)


# ── Startup/shutdown ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup checks before accepting requests."""
    log.info("AURA node starting…")
    try:
        check_ollama()
    except RuntimeError as exc:
        log.error("Startup check failed: %s", exc)
        # Don't crash – ingestion still works without Ollama
    yield
    log.info("AURA node shutting down.")


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

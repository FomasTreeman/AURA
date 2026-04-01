"""
Ingestion pipeline for AURA backend.
Orchestrates: PDF parse → PII redaction → chunking → embedding → ChromaDB storage.
"""
import uuid
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

from backend.config import (
    CHUNK_OVERLAP,
    EMBEDDING_MODEL,
    MAX_CHUNK_SIZE,
)
from backend.database.chroma import get_collection
from backend.ingestion.parser import parse_pdf
from backend.ingestion.redactor import redact
from backend.storage.ipfs_integration import compute_file_cid
from backend.utils.hashing import sha256_file
from backend.utils.logging import get_logger

log = get_logger(__name__)

# ── Module-level singletons (lazy-loaded on first ingest call) ────────────────
_splitter: RecursiveCharacterTextSplitter | None = None
_embedder: SentenceTransformer | None = None


def _get_splitter() -> RecursiveCharacterTextSplitter:
    """Return (or create) the text splitter singleton."""
    global _splitter
    if _splitter is None:
        _splitter = RecursiveCharacterTextSplitter(
            chunk_size=MAX_CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
        )
    return _splitter


def _get_embedder() -> SentenceTransformer:
    """Return (or create) the SentenceTransformer embedding model singleton."""
    global _embedder
    if _embedder is None:
        log.info("Loading embedding model '%s'…", EMBEDDING_MODEL)
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
        log.info("Embedding model loaded.")
    return _embedder


# ── Public API ────────────────────────────────────────────────────────────────

def ingest_file(path: Path) -> dict[str, int | str]:
    """
    Ingest a single PDF file into the AURA vector store.

    Pipeline steps:
      1. Compute SHA-256 CID of raw PDF bytes.
      2. Parse PDF page-by-page in batches of 20 pages.
      3. Redact PII from each page's text (Presidio).
      4. Chunk redacted text with overlap.
      5. Embed chunks with SentenceTransformer.
      6. Persist chunks + embeddings + metadata to ChromaDB.

    Args:
        path: Absolute path to the PDF file.

    Returns:
        Dict with keys: 'file', 'cid', 'chunks_added'.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        ValueError: If the file cannot be parsed as a PDF.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    cid = sha256_file(path)
    ipfs_cid = compute_file_cid(path)
    log.info("Ingesting '%s'  SHA256=%s…  IPFS=%s…", path.name, cid[:12], ipfs_cid[:16])

    splitter = _get_splitter()
    embedder = _get_embedder()
    collection = get_collection()

    total_chunks = 0

    for page_batch in parse_pdf(path):
        # --- Redact PII from each page ----------------------------------------
        redacted_pages = [redact(p.text) for p in page_batch]

        # --- Chunk each page's text -------------------------------------------
        all_chunks: list[str] = []
        all_meta: list[dict] = []

        for page_content, redacted_text in zip(page_batch, redacted_pages):
            chunks = splitter.split_text(redacted_text)
            for chunk in chunks:
                all_chunks.append(chunk)
                all_meta.append({
                    "source": path.name,
                    "page": page_content.page_num,
                    "cid": cid,
                    "ipfs_cid": ipfs_cid,
                })

        if not all_chunks:
            continue

        # --- Embed ------------------------------------------------------------
        embeddings = embedder.encode(
            all_chunks,
            show_progress_bar=False,
            normalize_embeddings=True,
        ).tolist()

        # --- Store in ChromaDB ------------------------------------------------
        ids = [str(uuid.uuid4()) for _ in all_chunks]
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=all_chunks,
            metadatas=all_meta,
        )
        total_chunks += len(all_chunks)

    log.info(
        "Ingested '%s': %d chunks stored (CID %s…)",
        path.name,
        total_chunks,
        cid[:12],
    )
    return {"file": path.name, "cid": cid, "ipfs_cid": ipfs_cid, "chunks_added": total_chunks}


def ingest_directory(directory: Path) -> list[dict[str, int | str]]:
    """
    Ingest all PDF files found in a directory (non-recursive).

    Args:
        directory: Path to a directory containing PDF files.

    Returns:
        List of result dicts from ingest_file, one per successfully ingested file.

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")

    pdfs = sorted(directory.glob("*.pdf"))
    if not pdfs:
        log.warning("No PDF files found in '%s'", directory)
        return []

    log.info("Found %d PDF(s) in '%s'", len(pdfs), directory)
    results = []
    for pdf in pdfs:
        try:
            result = ingest_file(pdf)
            results.append(result)
        except Exception as exc:
            log.error("Failed to ingest '%s': %s", pdf.name, exc)
            results.append({"file": pdf.name, "error": str(exc), "chunks_added": 0})

    return results

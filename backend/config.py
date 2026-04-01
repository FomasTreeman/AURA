"""
Configuration module for AURA backend.
Loads settings from .env and exposes typed constants.
"""
from pathlib import Path
from dotenv import load_dotenv
import os

# Load .env from project root (two levels up from this file)
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _get(key: str, default: str) -> str:
    """Return env var value or a default, resolving relative paths to project root."""
    return os.getenv(key, default)


def _resolve_path(raw: str) -> Path:
    """Resolve a path relative to the project root if not absolute."""
    p = Path(raw)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


# ── LLM ──────────────────────────────────────────────────────────────────────
OLLAMA_MODEL: str = _get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_BASE_URL: str = _get("OLLAMA_BASE_URL", "http://localhost:11434")

# ── Vector DB ─────────────────────────────────────────────────────────────────
CHROMA_PATH: Path = _resolve_path(_get("CHROMA_PATH", "./data/chroma_db"))
CHROMA_COLLECTION: str = "aura_documents"

# ── Ingestion ─────────────────────────────────────────────────────────────────
INGEST_DIR: Path = _resolve_path(_get("INGEST_DIR", "./data/documents"))
MAX_CHUNK_SIZE: int = int(_get("MAX_CHUNK_SIZE", "1000"))
CHUNK_OVERLAP: int = int(_get("CHUNK_OVERLAP", "200"))
BATCH_SIZE: int = 20  # pages per embedding batch (prevents OOM on large PDFs)

# ── Embedding ─────────────────────────────────────────────────────────────────
EMBEDDING_MODEL: str = _get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# ── Retrieval ─────────────────────────────────────────────────────────────────
RETRIEVAL_TOP_K: int = 5
RETRIEVAL_SCORE_THRESHOLD: float = 0.3

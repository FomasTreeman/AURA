"""
ChromaDB client singleton for AURA backend.
Always use get_collection() to access the persistent vector store.
"""

from __future__ import annotations

import chromadb
from chromadb import Collection
from typing import TYPE_CHECKING

from backend.config import CHROMA_PATH, CHROMA_COLLECTION
from backend.utils.logging import get_logger

if TYPE_CHECKING:
    from chromadb import PersistentClient

log = get_logger(__name__)

_client: PersistentClient | None = None


def get_client() -> PersistentClient:
    """
    Return (or lazily create) the global ChromaDB PersistentClient.

    Returns:
        Singleton chromadb.PersistentClient instance.
    """
    global _client
    if _client is None:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        log.debug("ChromaDB client opened at %s", CHROMA_PATH)
    return _client


def get_collection() -> Collection:
    """
    Return the AURA documents collection, creating it if it does not exist.

    Returns:
        ChromaDB Collection named 'aura_documents'.
    """
    client = get_client()
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def reset_collection() -> Collection:
    """
    Delete and re-create the AURA documents collection.
    Useful for testing and full re-ingestion.

    Returns:
        Fresh empty Collection.
    """
    client = get_client()
    try:
        client.delete_collection(CHROMA_COLLECTION)
        log.info("Deleted existing collection '%s'", CHROMA_COLLECTION)
    except Exception:
        pass
    return get_collection()

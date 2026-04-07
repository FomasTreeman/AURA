"""
RAG retriever for AURA backend.
Performs cosine similarity search in ChromaDB using SentenceTransformer embeddings.
"""
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from backend.config import EMBEDDING_MODEL, RETRIEVAL_SCORE_THRESHOLD, RETRIEVAL_TOP_K
from backend.database.chroma import get_collection
from backend.utils.logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_embedder() -> SentenceTransformer:
    """Lazily load and cache the SentenceTransformer embedding model."""
    log.info("Loading retrieval embedding model '%s'…", EMBEDDING_MODEL)
    model = SentenceTransformer(EMBEDDING_MODEL)
    log.info("Retrieval embedding model ready.")
    return model


def retrieve(
    question: str,
    top_k: int = RETRIEVAL_TOP_K,
    score_threshold: float = RETRIEVAL_SCORE_THRESHOLD,
) -> list[dict]:
    """
    Retrieve the most relevant document chunks for a given question.

    Embeds the question with the same model used during ingestion, then queries
    ChromaDB for the top-k most similar chunks. Chunks with a cosine distance
    above the threshold (i.e., low similarity) are filtered out.

    Args:
        question: User question string.
        top_k: Maximum number of chunks to return.
        score_threshold: Maximum cosine distance to accept (lower = more similar).
                         Chunks with distance > threshold are discarded.

    Returns:
        List of dicts, each containing:
          - 'text': chunk text
          - 'source': filename
          - 'page': page number (int)
          - 'cid': document SHA-256 hash
          - 'distance': cosine distance score (float, lower is better)
    """
    embedder = _get_embedder()
    collection = get_collection()

    if collection.count() == 0:
        log.warning("ChromaDB collection is empty — no documents ingested yet.")
        return []

    query_embedding = embedder.encode(
        question,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[dict] = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for doc, meta, dist in zip(docs, metas, distances):
        if dist > score_threshold:
            continue
        chunks.append({
            "text": doc,
            "source": meta.get("source", "unknown"),
            "page": meta.get("page", 0),
            "cid": meta.get("cid", ""),
            "distance": round(dist, 4),
        })

    log.info(
        "Retrieved %d/%d chunks for query (threshold=%.2f)",
        len(chunks),
        top_k,
        score_threshold,
    )
    return chunks

"""
Reciprocal Rank Fusion (RRF) for AURA federated retrieval.

RRF merges multiple ranked lists of document chunks into a single
deterministic ranking, without requiring calibrated scores across nodes.

Formula (Cormack et al., 2009):
    RRF_score(d) = Σ  1 / (k + rank_i(d))
                   i
where rank_i(d) is the 1-based rank of document d in list i,
and k is a smoothing constant (default 60).

Each chunk must carry a 'chunk_id' key — a stable identifier derived from
the document's CID and the chunk's text hash. Chunks with the same chunk_id
from different ranking lists are merged (scores accumulated, metadata kept
from first occurrence).
"""
import hashlib
from typing import Any

from backend.utils.logging import get_logger

log = get_logger(__name__)

_DEFAULT_K = 60


def make_chunk_id(cid: str, text: str) -> str:
    """
    Derive a stable, content-addressed chunk identifier.

    Args:
        cid: SHA-256 CID of the source document.
        text: The chunk text content.

    Returns:
        First 16 hex characters of SHA-256(cid + text).
    """
    return hashlib.sha256(f"{cid}:{text}".encode()).hexdigest()[:16]


def assign_chunk_ids(chunks: list[dict]) -> list[dict]:
    """
    Ensure every chunk in a list has a 'chunk_id' field.

    Mutates chunks in-place and also returns the list.

    Args:
        chunks: List of chunk dicts from retriever output.

    Returns:
        Same list with 'chunk_id' populated on each item.
    """
    for chunk in chunks:
        if "chunk_id" not in chunk:
            chunk["chunk_id"] = make_chunk_id(
                chunk.get("cid", ""),
                chunk.get("text", ""),
            )
    return chunks


def rrf_fuse(
    rankings: list[list[dict]],
    k: int = _DEFAULT_K,
    top_k: int | None = None,
) -> list[dict]:
    """
    Apply Reciprocal Rank Fusion across multiple ranked chunk lists.

    Each list in `rankings` represents one node's ordered results (best first).
    Chunks must have a 'chunk_id' field; call assign_chunk_ids() first if needed.

    The fusion is fully deterministic: for equal RRF scores, chunks are
    ordered by chunk_id (lexicographic) to ensure stability.

    Args:
        rankings: List of ranked lists. Each inner list is ordered best → worst.
                  Empty inner lists are skipped.
        k:        RRF constant. Higher k → flatter scoring curve (less emphasis
                  on top-rank advantage). Default 60 (original paper default).
        top_k:    If provided, return only the top_k chunks after fusion.

    Returns:
        Fused list of chunk dicts sorted by rrf_score descending. Each dict
        carries the original chunk fields plus:
          - 'rrf_score': float — the accumulated RRF score.
          - 'rrf_sources': int — number of ranking lists the chunk appeared in.
    """
    if not rankings:
        return []

    scores: dict[str, float] = {}
    source_counts: dict[str, int] = {}
    items: dict[str, dict] = {}   # chunk_id → first-seen item dict

    for ranking in rankings:
        if not ranking:
            continue
        for rank, chunk in enumerate(ranking, 1):
            chunk_id = chunk.get("chunk_id")
            if not chunk_id:
                log.warning("Chunk missing 'chunk_id', skipping in RRF")
                continue
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            source_counts[chunk_id] = source_counts.get(chunk_id, 0) + 1
            if chunk_id not in items:
                items[chunk_id] = dict(chunk)

    if not scores:
        return []

    # Sort: primary by rrf_score (desc), secondary by chunk_id (asc, for determinism)
    sorted_ids = sorted(
        scores.keys(),
        key=lambda cid: (-scores[cid], cid),
    )

    result: list[dict] = []
    for chunk_id in sorted_ids:
        entry = dict(items[chunk_id])
        entry["rrf_score"] = round(scores[chunk_id], 8)
        entry["rrf_sources"] = source_counts[chunk_id]
        result.append(entry)

    if top_k is not None:
        result = result[:top_k]

    log.debug(
        "RRF fused %d lists → %d unique chunks (top=%s, k=%d)",
        len(rankings),
        len(result),
        top_k,
        k,
    )
    return result


def normalize_scores(chunks: list[dict], score_key: str = "distance") -> list[dict]:
    """
    Apply min-max normalization to a score field across a chunk list.

    Converts distances (lower = better) to similarities (higher = better)
    with the formula: similarity = 1 - (distance - min) / (max - min).

    Args:
        chunks: List of chunk dicts.
        score_key: Dict key holding the raw score to normalize.

    Returns:
        New list of dicts with 'normalized_score' field added (0..1, higher is better).
    """
    if not chunks:
        return []

    values = [c.get(score_key, 0.0) for c in chunks]
    min_val = min(values)
    max_val = max(values)
    span = max_val - min_val

    result = []
    for chunk in chunks:
        entry = dict(chunk)
        raw = chunk.get(score_key, 0.0)
        if span > 0:
            # Distance → similarity: invert so lower distance = higher score
            entry["normalized_score"] = round(1.0 - (raw - min_val) / span, 6)
        else:
            entry["normalized_score"] = 1.0
        result.append(entry)
    return result

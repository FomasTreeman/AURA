"""
Consensus and data-hygiene policies for AURA federated retrieval.

Responsibilities:
  - Deduplication: remove duplicate chunks by chunk_id across merged lists.
  - Tombstoning: filter out chunks from documents that have been revoked/deleted
    (pub/sub revocation in Resilience; Federated RAG provides the enforcement stub).
  - TTL enforcement: drop chunks whose source document was ingested beyond a
    configurable age (future use).
  - Provenance tagging: annotate each chunk with the node_id(s) that returned it.
"""

import hashlib
import time
from typing import Callable

from backend.utils.logging import get_logger

log = get_logger(__name__)

# Module-level in-memory tombstone set (populated via P2P pub/sub in Resilience)
_tombstoned_cids: set[str] = set()


# ── Tombstone management ──────────────────────────────────────────────────────


def add_tombstone(cid: str) -> None:
    """
    Mark a document CID as revoked. Chunks from this document will be
    filtered out by apply_tombstones().

    Args:
        cid: SHA-256 content ID of the document to revoke.
    """
    _tombstoned_cids.add(cid)
    log.info("Tombstoned CID: %s", cid[:16])


def remove_tombstone(cid: str) -> None:
    """Reinstate a previously tombstoned CID (e.g. on re-ingest)."""
    _tombstoned_cids.discard(cid)


def get_tombstones() -> frozenset[str]:
    """Return an immutable snapshot of the current tombstone set."""
    return frozenset(_tombstoned_cids)


def apply_tombstones(
    chunks: list[dict],
    extra_tombstones: set[str] | None = None,
) -> list[dict]:
    """
    Filter out chunks whose source document has been revoked.

    Args:
        chunks: List of chunk dicts, each with a 'cid' field.
        extra_tombstones: Additional CIDs to treat as tombstoned (e.g. from peers).

    Returns:
        Filtered list with tombstoned chunks removed.
    """
    tombstones = _tombstoned_cids | (extra_tombstones or set())
    if not tombstones:
        return chunks

    original_len = len(chunks)
    result = [c for c in chunks if c.get("cid", "") not in tombstones]
    removed = original_len - len(result)
    if removed:
        log.info("Tombstone filter: removed %d chunk(s)", removed)
    return result


# ── Deduplication ─────────────────────────────────────────────────────────────


def deduplicate(chunks: list[dict]) -> list[dict]:
    """
    Remove duplicate chunks by chunk_id, preserving first occurrence order.

    When the same chunk appears from multiple peers, we keep the first
    occurrence's metadata but merge the 'node_ids' provenance list.

    Args:
        chunks: List of chunk dicts. Each must have a 'chunk_id' field.

    Returns:
        Deduplicated list.
    """
    seen: dict[str, dict] = {}  # chunk_id → kept chunk
    result: list[dict] = []

    for chunk in chunks:
        chunk_id = chunk.get("chunk_id")
        if not chunk_id:
            result.append(chunk)
            continue

        if chunk_id not in seen:
            entry = dict(chunk)
            # Normalise provenance to a list
            if "node_id" in entry and "node_ids" not in entry:
                entry["node_ids"] = [entry.pop("node_id")]
            elif "node_ids" not in entry:
                entry["node_ids"] = []
            seen[chunk_id] = entry
            result.append(entry)
        else:
            # Merge provenance
            existing = seen[chunk_id]
            new_node = chunk.get("node_id") or chunk.get("node_ids", [])
            if isinstance(new_node, str):
                new_node = [new_node]
            for nid in new_node:
                if nid and nid not in existing.get("node_ids", []):
                    existing.setdefault("node_ids", []).append(nid)

    log.debug(
        "Deduplication: %d → %d chunks (%d removed)",
        len(chunks),
        len(result),
        len(chunks) - len(result),
    )
    return result


# ── Score normalization ───────────────────────────────────────────────────────


def normalize_scores_per_node(
    chunks: list[dict],
    score_key: str = "distance",
) -> list[dict]:
    """
    Apply per-node min-max normalization to chunk scores.

    Each node's scores are normalized independently to [0, 1] before
    being passed to RRF. This prevents a node with consistently high
    distances from dominating the fusion.

    Args:
        chunks: Flat list of chunks. Each must have 'node_id' and the score_key.
        score_key: Field name of the raw score.

    Returns:
        New list with 'normalized_score' added (1.0 = best, 0.0 = worst).
    """
    # Group by node_id
    by_node: dict[str, list[dict]] = {}
    for chunk in chunks:
        nid = chunk.get("node_id", "local")
        by_node.setdefault(nid, []).append(chunk)

    result: list[dict] = []
    for nid, node_chunks in by_node.items():
        values = [c.get(score_key, 0.0) for c in node_chunks]
        min_v, max_v = min(values), max(values)
        span = max_v - min_v
        for chunk in node_chunks:
            entry = dict(chunk)
            raw = chunk.get(score_key, 0.0)
            if span > 0:
                entry["normalized_score"] = round(1.0 - (raw - min_v) / span, 6)
            else:
                entry["normalized_score"] = 1.0
            result.append(entry)

    return result


# ── Provenance tagging ────────────────────────────────────────────────────────


def tag_provenance(chunks: list[dict], node_id: str) -> list[dict]:
    """
    Tag each chunk with the node_id that returned it.

    Args:
        chunks: List of chunk dicts.
        node_id: The peer_id (or 'local') of the node that produced the chunks.

    Returns:
        New list of dicts with 'node_id' set.
    """
    return [{**chunk, "node_id": node_id} for chunk in chunks]

"""
Unit tests for backend.rag.consensus.
Covers: deduplication, tombstoning, per-node score normalization, provenance tagging.
"""
import pytest

from backend.rag.consensus import (
    add_tombstone,
    apply_tombstones,
    deduplicate,
    get_tombstones,
    normalize_scores_per_node,
    remove_tombstone,
    tag_provenance,
)
from backend.rag.rrf import make_chunk_id


def _chunk(text: str, cid: str = "cid1", **extra) -> dict:
    return {
        "text": text,
        "cid": cid,
        "chunk_id": make_chunk_id(cid, text),
        "source": f"{cid}.pdf",
        "page": 1,
        **extra,
    }


# ── Tombstone tests ───────────────────────────────────────────────────────────

class TestTombstones:
    """Tests for tombstone management functions."""

    def setup_method(self):
        """Clear tombstones before each test."""
        import backend.rag.consensus as m
        m._tombstoned_cids.clear()

    def test_add_and_get_tombstone(self):
        """add_tombstone() should persist the CID in the tombstone set."""
        add_tombstone("abc123")
        assert "abc123" in get_tombstones()

    def test_remove_tombstone(self):
        """remove_tombstone() should remove a CID from the tombstone set."""
        add_tombstone("abc123")
        remove_tombstone("abc123")
        assert "abc123" not in get_tombstones()

    def test_apply_tombstones_filters_revoked(self):
        """Chunks whose CID is tombstoned must be removed."""
        add_tombstone("bad_cid")
        chunks = [
            _chunk("good text", cid="good_cid"),
            _chunk("bad text", cid="bad_cid"),
        ]
        result = apply_tombstones(chunks)
        assert len(result) == 1
        assert result[0]["cid"] == "good_cid"

    def test_apply_tombstones_no_tombstones(self):
        """If no tombstones set, all chunks pass through."""
        chunks = [_chunk("text", cid="cid1"), _chunk("text2", cid="cid2")]
        result = apply_tombstones(chunks)
        assert len(result) == 2

    def test_apply_extra_tombstones(self):
        """Extra tombstones passed as argument are also applied."""
        chunks = [_chunk("text", cid="peer_revoked")]
        result = apply_tombstones(chunks, extra_tombstones={"peer_revoked"})
        assert result == []

    def test_tombstone_does_not_affect_other_cids(self):
        """Tombstoning one CID must not affect chunks with different CIDs."""
        add_tombstone("only_this")
        chunks = [_chunk("safe", cid="safe_cid")]
        result = apply_tombstones(chunks)
        assert len(result) == 1


# ── Deduplication tests ───────────────────────────────────────────────────────

class TestDeduplicate:
    """Tests for deduplicate()."""

    def test_no_duplicates_unchanged(self):
        """List with no duplicates must be returned unchanged."""
        chunks = [_chunk(f"text {i}", f"cid{i}") for i in range(5)]
        result = deduplicate(chunks)
        assert len(result) == 5

    def test_duplicate_chunk_ids_removed(self):
        """Chunks with the same chunk_id must be deduplicated."""
        c = _chunk("repeated text", cid="doc1")
        chunks = [c, dict(c), dict(c)]  # same chunk_id three times
        result = deduplicate(chunks)
        assert len(result) == 1

    def test_first_occurrence_preserved(self):
        """First occurrence of a duplicate is the one kept."""
        c1 = _chunk("text", cid="d1")
        c1["node_id"] = "peer_A"
        c2 = dict(c1)
        c2["node_id"] = "peer_B"
        result = deduplicate([c1, c2])
        assert len(result) == 1
        # node_ids should be merged
        assert "peer_A" in result[0].get("node_ids", []) or result[0].get("node_id") == "peer_A"

    def test_preserves_order(self):
        """Deduplication preserves original ordering of unique items."""
        chunks = [_chunk(f"chunk {i}", f"cid{i}") for i in [3, 1, 4, 1, 5]]
        result = deduplicate(chunks)
        # Should see chunk_ids for cid3, cid1, cid4, cid5 in order
        texts = [c["text"] for c in result]
        assert texts.index("chunk 3") < texts.index("chunk 1")
        assert texts.index("chunk 1") < texts.index("chunk 4")
        assert texts.index("chunk 4") < texts.index("chunk 5")

    def test_chunks_without_chunk_id_are_kept(self):
        """Chunks with no chunk_id are included as-is (no dedup possible)."""
        chunks = [{"text": "no id"}]
        result = deduplicate(chunks)
        assert len(result) == 1

    def test_provenance_merge(self):
        """When a chunk appears from multiple nodes, node_ids are merged."""
        c = _chunk("text", cid="d1")
        copy_a = {**c, "node_id": "nodeA"}
        copy_b = {**c, "node_id": "nodeB"}
        result = deduplicate([copy_a, copy_b])
        assert len(result) == 1
        node_ids = result[0].get("node_ids", [])
        assert "nodeA" in node_ids
        assert "nodeB" in node_ids


# ── Score normalization tests ─────────────────────────────────────────────────

class TestNormalizeScoresPerNode:
    """Tests for normalize_scores_per_node()."""

    def test_empty_returns_empty(self):
        assert normalize_scores_per_node([]) == []

    def test_per_node_normalization(self):
        """Each node's scores are normalized independently."""
        chunks = [
            {"distance": 0.1, "node_id": "A"},
            {"distance": 0.9, "node_id": "A"},
            {"distance": 0.5, "node_id": "B"},
            {"distance": 0.8, "node_id": "B"},
        ]
        result = normalize_scores_per_node(chunks, score_key="distance")
        # Within node A, distance 0.1 should get score 1.0 (best)
        by_id = {(c["node_id"], c["distance"]): c["normalized_score"] for c in result}
        assert by_id[("A", 0.1)] > by_id[("A", 0.9)]
        assert by_id[("B", 0.5)] > by_id[("B", 0.8)]

    def test_all_scores_in_0_1_range(self):
        """All normalized_scores must be in [0, 1]."""
        chunks = [
            {"distance": d, "node_id": "local"}
            for d in [0.0, 0.3, 0.7, 1.0]
        ]
        result = normalize_scores_per_node(chunks)
        for c in result:
            assert 0.0 <= c["normalized_score"] <= 1.0


# ── Provenance tagging tests ──────────────────────────────────────────────────

class TestTagProvenance:
    """Tests for tag_provenance()."""

    def test_tags_all_chunks(self):
        """All chunks get the node_id tag."""
        chunks = [_chunk(f"text {i}") for i in range(3)]
        result = tag_provenance(chunks, node_id="peer_xyz")
        assert all(c["node_id"] == "peer_xyz" for c in result)

    def test_returns_new_list(self):
        """Returns new list objects, not mutating originals."""
        original = [_chunk("text")]
        result = tag_provenance(original, node_id="my_node")
        assert result[0] is not original[0]

    def test_preserves_existing_fields(self):
        """Original fields must be preserved alongside the new node_id."""
        chunks = [{"text": "hello", "source": "doc.pdf"}]
        result = tag_provenance(chunks, node_id="N1")
        assert result[0]["text"] == "hello"
        assert result[0]["source"] == "doc.pdf"
        assert result[0]["node_id"] == "N1"

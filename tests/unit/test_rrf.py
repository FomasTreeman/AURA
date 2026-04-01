"""
Unit tests for backend.rag.rrf.
Covers: RRF algorithm correctness, determinism, edge cases, chunk_id assignment.
"""
import pytest

from backend.rag.rrf import (
    assign_chunk_ids,
    make_chunk_id,
    normalize_scores,
    rrf_fuse,
)


def _chunk(text: str, cid: str = "doc1", **extra) -> dict:
    """Helper to build a chunk dict with a chunk_id."""
    c = {"text": text, "cid": cid, "source": f"{cid}.pdf", "page": 1, **extra}
    c["chunk_id"] = make_chunk_id(cid, text)
    return c


class TestMakeChunkId:
    """Tests for make_chunk_id()."""

    def test_deterministic(self):
        """Same inputs always produce the same chunk_id."""
        assert make_chunk_id("doc1", "hello") == make_chunk_id("doc1", "hello")

    def test_different_cid_different_id(self):
        """Different CIDs for the same text produce different chunk_ids."""
        assert make_chunk_id("doc1", "text") != make_chunk_id("doc2", "text")

    def test_different_text_different_id(self):
        """Different text for the same CID produces different chunk_ids."""
        assert make_chunk_id("doc1", "aaa") != make_chunk_id("doc1", "bbb")

    def test_output_is_16_hex_chars(self):
        """chunk_id must be exactly 16 hex characters."""
        cid = make_chunk_id("cid", "text")
        assert len(cid) == 16
        assert all(c in "0123456789abcdef" for c in cid)


class TestAssignChunkIds:
    """Tests for assign_chunk_ids()."""

    def test_adds_chunk_id_when_missing(self):
        """Chunks without chunk_id get one assigned."""
        chunks = [{"text": "hello", "cid": "abc"}]
        assign_chunk_ids(chunks)
        assert "chunk_id" in chunks[0]

    def test_preserves_existing_chunk_id(self):
        """Existing chunk_id is not overwritten."""
        chunks = [{"text": "hello", "cid": "abc", "chunk_id": "manual_id"}]
        assign_chunk_ids(chunks)
        assert chunks[0]["chunk_id"] == "manual_id"

    def test_returns_same_list(self):
        """Returns the same list object."""
        original = [{"text": "x", "cid": "y"}]
        returned = assign_chunk_ids(original)
        assert returned is original


class TestRrfFuse:
    """Tests for rrf_fuse()."""

    def test_empty_rankings_returns_empty(self):
        """Empty input must return empty list."""
        assert rrf_fuse([]) == []

    def test_all_empty_inner_lists_returns_empty(self):
        """All-empty inner lists must return empty."""
        assert rrf_fuse([[], [], []]) == []

    def test_single_list_passthrough(self):
        """Single ranking list should pass through in order."""
        ranking = [_chunk(f"text {i}", f"doc{i}") for i in range(5)]
        fused = rrf_fuse([ranking])
        assert len(fused) == 5
        # First chunk in input should have highest RRF score
        assert fused[0]["chunk_id"] == ranking[0]["chunk_id"]

    def test_higher_ranked_gets_higher_score(self):
        """Top-ranked items across lists must accumulate higher scores."""
        a = _chunk("top result", cid="top_doc")
        b = _chunk("second result", cid="second_doc")
        # Both lists rank 'a' first
        list1 = [a, b]
        list2 = [a, b]
        fused = rrf_fuse([list1, list2])
        scores = {c["chunk_id"]: c["rrf_score"] for c in fused}
        assert scores[a["chunk_id"]] > scores[b["chunk_id"]]

    def test_chunk_appearing_in_two_lists_has_higher_score(self):
        """A chunk in 2 lists beats a chunk in only 1 list at equal rank."""
        shared = _chunk("shared content", cid="shared")
        only_a = _chunk("only in A", cid="only_a")
        only_b = _chunk("only in B", cid="only_b")
        list1 = [shared, only_a]
        list2 = [shared, only_b]
        fused = rrf_fuse([list1, list2])
        scores = {c["chunk_id"]: c["rrf_score"] for c in fused}
        # shared is rank 1 in both lists → highest score
        assert fused[0]["chunk_id"] == shared["chunk_id"]
        assert scores[shared["chunk_id"]] > scores[only_a["chunk_id"]]
        assert scores[shared["chunk_id"]] > scores[only_b["chunk_id"]]

    def test_determinism_across_runs(self):
        """Same inputs must produce identical output across 10 runs."""
        list1 = [_chunk(f"chunk {i}", f"d{i}") for i in range(5)]
        list2 = [_chunk(f"chunk {j}", f"d{j}") for j in range(3, 8)]
        results = [rrf_fuse([list1, list2]) for _ in range(10)]
        ids_0 = [c["chunk_id"] for c in results[0]]
        for result in results[1:]:
            assert [c["chunk_id"] for c in result] == ids_0

    def test_top_k_limits_output(self):
        """top_k parameter must limit output length."""
        ranking = [_chunk(f"chunk {i}", f"doc{i}") for i in range(10)]
        fused = rrf_fuse([ranking], top_k=3)
        assert len(fused) == 3

    def test_rrf_score_field_present(self):
        """Every output chunk must have an rrf_score float field."""
        ranking = [_chunk("text", "doc1")]
        fused = rrf_fuse([ranking])
        assert "rrf_score" in fused[0]
        assert isinstance(fused[0]["rrf_score"], float)

    def test_rrf_sources_field_present(self):
        """Every output chunk must have rrf_sources counting its appearances."""
        a = _chunk("shared", cid="s")
        fused = rrf_fuse([[a], [a]])
        assert fused[0]["rrf_sources"] == 2

    def test_known_rrf_score_calculation(self):
        """Verify RRF score matches manual calculation for k=60."""
        # Rank 1 in list 1: score = 1/(60+1) = 1/61
        # Rank 1 in list 2: score = 1/(60+1) = 1/61
        # Total = 2/61 ≈ 0.032786885
        a = _chunk("shared", cid="a")
        fused = rrf_fuse([[a], [a]], k=60)
        expected = 2.0 / 61.0
        assert abs(fused[0]["rrf_score"] - expected) < 1e-6

    def test_custom_k_affects_scores(self):
        """Changing k must change RRF scores."""
        ranking = [_chunk("x", "d1")]
        fused_k60 = rrf_fuse([ranking], k=60)
        fused_k1 = rrf_fuse([ranking], k=1)
        assert fused_k60[0]["rrf_score"] != fused_k1[0]["rrf_score"]

    def test_missing_chunk_id_skipped(self):
        """Chunks without chunk_id are silently skipped."""
        bad = {"text": "no id", "cid": "x"}  # no chunk_id
        good = _chunk("good chunk", "doc1")
        fused = rrf_fuse([[bad, good]])
        chunk_ids = [c["chunk_id"] for c in fused]
        assert good["chunk_id"] in chunk_ids

    def test_preserves_original_metadata(self):
        """Fused chunks must retain all original fields from the source chunk."""
        chunk = _chunk("important text", cid="my_cid")
        chunk["source"] = "report.pdf"
        chunk["page"] = 5
        fused = rrf_fuse([[chunk]])
        assert fused[0]["source"] == "report.pdf"
        assert fused[0]["page"] == 5


class TestNormalizeScores:
    """Tests for normalize_scores()."""

    def test_empty_returns_empty(self):
        assert normalize_scores([]) == []

    def test_single_item_gets_1(self):
        """Single item has normalized_score = 1.0 (no range to normalize)."""
        chunks = [{"distance": 0.5}]
        result = normalize_scores(chunks, score_key="distance")
        assert result[0]["normalized_score"] == 1.0

    def test_min_distance_gets_highest_score(self):
        """Lower distance → higher normalized_score."""
        chunks = [{"distance": 0.1}, {"distance": 0.9}]
        result = normalize_scores(chunks, score_key="distance")
        # distance 0.1 should get normalized_score close to 1.0
        scores = {c["distance"]: c["normalized_score"] for c in result}
        assert scores[0.1] > scores[0.9]

    def test_scores_in_zero_one_range(self):
        """All normalized scores must be in [0, 1]."""
        chunks = [{"distance": d} for d in [0.0, 0.25, 0.5, 0.75, 1.0]]
        result = normalize_scores(chunks, score_key="distance")
        for c in result:
            assert 0.0 <= c["normalized_score"] <= 1.0

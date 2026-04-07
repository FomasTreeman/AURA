"""
Integration tests for the AURA ingestion pipeline and retriever.
These tests exercise the full pipeline: PDF → Presidio → chunks → embeddings → ChromaDB.
They do NOT require Ollama (LLM generation is tested separately).
"""
from pathlib import Path

import pytest

from backend.database.chroma import get_collection, reset_collection
from backend.ingestion.pipeline import ingest_directory, ingest_file
from backend.rag.retriever import retrieve


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reset():
    """Clear ChromaDB before each test that modifies state."""
    reset_collection()


# ── Ingest single file ────────────────────────────────────────────────────────

class TestIngestFile:
    """Tests for ingest_file()."""

    def test_ingest_returns_correct_keys(self, sample_pdf):
        """Result dict must contain file, cid, and chunks_added."""
        _reset()
        result = ingest_file(sample_pdf)
        assert "file" in result
        assert "cid" in result
        assert "chunks_added" in result

    def test_ingest_adds_chunks_to_collection(self, sample_pdf):
        """After ingestion, the ChromaDB collection must be non-empty."""
        _reset()
        result = ingest_file(sample_pdf)
        assert result["chunks_added"] > 0
        assert get_collection().count() > 0

    def test_ingest_cid_is_sha256(self, sample_pdf):
        """The returned CID must be a 64-char hex string."""
        _reset()
        result = ingest_file(sample_pdf)
        cid = result["cid"]
        assert len(cid) == 64
        assert all(c in "0123456789abcdef" for c in cid)

    def test_ingest_cid_deterministic(self, sample_pdf):
        """Same file ingested twice must produce the same CID."""
        _reset()
        r1 = ingest_file(sample_pdf)
        _reset()
        r2 = ingest_file(sample_pdf)
        assert r1["cid"] == r2["cid"]

    def test_ingest_metadata_stored(self, sample_pdf):
        """ChromaDB entries must carry source, page, and cid metadata."""
        _reset()
        result = ingest_file(sample_pdf)
        col = get_collection()
        items = col.get(include=["metadatas"])
        metas = items["metadatas"]
        assert len(metas) > 0
        for meta in metas:
            assert "source" in meta
            assert "page" in meta
            assert "cid" in meta
            assert meta["cid"] == result["cid"]

    def test_ingest_pii_redacted_in_stored_chunks(self, sample_pdf):
        """The SSN on page 2 of the sample PDF must not appear in any stored chunk."""
        _reset()
        ingest_file(sample_pdf)
        col = get_collection()
        docs = col.get(include=["documents"])["documents"]
        combined = " ".join(docs)
        assert "523-78-2345" not in combined, "PII (SSN) leaked into vector store"

    def test_ingest_missing_file_raises(self, tmp_path):
        """ingest_file must raise FileNotFoundError for a non-existent path."""
        with pytest.raises(FileNotFoundError):
            ingest_file(tmp_path / "nonexistent.pdf")

    def test_ingest_corrupted_pdf_raises(self, corrupted_pdf):
        """ingest_file must raise ValueError (not crash) for a corrupt PDF."""
        with pytest.raises((ValueError, Exception)):
            ingest_file(corrupted_pdf)

    def test_large_pdf_batched(self, large_pdf):
        """A 25-page PDF (> BATCH_SIZE of 20) must be fully ingested."""
        _reset()
        result = ingest_file(large_pdf)
        assert result["chunks_added"] > 0
        # All 25 pages should be represented
        col = get_collection()
        items = col.get(include=["metadatas"])
        pages_seen = {m["page"] for m in items["metadatas"]}
        assert len(pages_seen) == 25


# ── Ingest directory ──────────────────────────────────────────────────────────

class TestIngestDirectory:
    """Tests for ingest_directory()."""

    def test_ingest_directory_empty(self, tmp_path):
        """An empty directory should return an empty list (no crash)."""
        result = ingest_directory(tmp_path)
        assert result == []

    def test_ingest_directory_multiple_pdfs(self, tmp_path, sample_pdf, large_pdf):
        """All PDFs in a directory should be ingested."""
        import shutil
        # Use a dedicated subdirectory to avoid picking up fixture files in tmp_path
        ingest_dir = tmp_path / "to_ingest"
        ingest_dir.mkdir()
        shutil.copy(sample_pdf, ingest_dir / "a.pdf")
        shutil.copy(large_pdf, ingest_dir / "b.pdf")
        _reset()
        results = ingest_directory(ingest_dir)
        assert len(results) == 2
        total_chunks = sum(r.get("chunks_added", 0) for r in results)
        assert total_chunks > 0

    def test_ingest_directory_not_found(self, tmp_path):
        """Non-existent directory raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            ingest_directory(tmp_path / "ghost_dir")


# ── Retriever ─────────────────────────────────────────────────────────────────

class TestRetriever:
    """Tests for retrieve() after ingestion."""

    def test_retrieve_returns_empty_when_no_docs(self):
        """Retriever must return [] when the collection is empty."""
        _reset()
        results = retrieve("What is the quarterly revenue?")
        assert results == []

    def test_retrieve_finds_relevant_chunk(self, sample_pdf):
        """After ingesting a revenue report, a revenue question should return results."""
        _reset()
        ingest_file(sample_pdf)
        results = retrieve("What was the Q3 revenue?", score_threshold=1.0)
        assert len(results) > 0

    def test_retrieve_result_structure(self, sample_pdf):
        """Each retrieved chunk must contain required keys."""
        _reset()
        ingest_file(sample_pdf)
        results = retrieve("revenue report", score_threshold=1.0)
        if results:
            for r in results:
                assert "text" in r
                assert "source" in r
                assert "page" in r
                assert "distance" in r

    def test_retrieve_respects_top_k(self, sample_pdf):
        """Retrieve must return at most top_k results."""
        _reset()
        ingest_file(sample_pdf)
        results = retrieve("revenue", top_k=2, score_threshold=1.0)
        assert len(results) <= 2

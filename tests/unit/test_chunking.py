"""
Unit tests for the chunking stage of the AURA ingestion pipeline.
Verifies chunk size, overlap, and boundary behaviour of RecursiveCharacterTextSplitter.
"""
import pytest
from langchain_text_splitters import RecursiveCharacterTextSplitter


def make_splitter(chunk_size: int = 100, chunk_overlap: int = 20) -> RecursiveCharacterTextSplitter:
    """Helper – create a splitter with explicit params for test isolation."""
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )


class TestChunkSize:
    """Verify that no chunk exceeds the configured maximum size."""

    def test_chunks_respect_max_size(self):
        """Each chunk must be <= chunk_size characters."""
        splitter = make_splitter(chunk_size=100, chunk_overlap=20)
        text = "word " * 200  # 1000 chars
        chunks = splitter.split_text(text)
        assert all(len(c) <= 100 for c in chunks), (
            f"Chunk too large: {max(len(c) for c in chunks)} chars"
        )

    def test_single_short_text_not_split(self):
        """Text shorter than chunk_size should not be split."""
        splitter = make_splitter(chunk_size=500, chunk_overlap=50)
        text = "Short document."
        chunks = splitter.split_text(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_exact_size_boundary(self):
        """Text exactly at chunk_size should produce one chunk."""
        splitter = make_splitter(chunk_size=50, chunk_overlap=0)
        text = "a" * 50
        chunks = splitter.split_text(text)
        assert len(chunks) == 1


class TestChunkOverlap:
    """Verify the overlap guarantee between consecutive chunks."""

    def test_overlap_content_present(self):
        """The end of chunk[i] should appear at the start of chunk[i+1]."""
        splitter = make_splitter(chunk_size=50, chunk_overlap=20)
        # Construct text that guarantees multiple chunks
        text = "abcde " * 50  # 300 chars
        chunks = splitter.split_text(text)
        assert len(chunks) >= 2, "Expected multiple chunks"

        for i in range(len(chunks) - 1):
            # The last `overlap` chars of chunk[i] should appear somewhere in chunk[i+1]
            tail = chunks[i][-20:].strip()
            if tail:
                assert tail in chunks[i + 1], (
                    f"Overlap not found between chunk {i} and {i+1}"
                )

    def test_zero_overlap_no_repetition(self):
        """With chunk_overlap=0, no character should appear in two consecutive chunks."""
        splitter = make_splitter(chunk_size=50, chunk_overlap=0)
        text = "x" * 200
        chunks = splitter.split_text(text)
        # total chars across all chunks should equal original (no duplication)
        assert sum(len(c) for c in chunks) == len(text)


class TestChunkProductionSettings:
    """Test with the production chunk_size=1000, chunk_overlap=200."""

    def test_production_params_produce_multiple_chunks(self):
        """A 5000-char document should be split into multiple chunks."""
        splitter = make_splitter(chunk_size=1000, chunk_overlap=200)
        text = "This is a sentence about enterprise data governance. " * 100
        chunks = splitter.split_text(text)
        assert len(chunks) >= 4

    def test_all_content_preserved(self):
        """
        The union of all chunks should cover all words from the original text.
        (Overlap means total chars > original, but all words are present.)
        """
        splitter = make_splitter(chunk_size=1000, chunk_overlap=200)
        words = ["word" + str(i) for i in range(300)]
        text = " ".join(words)
        chunks = splitter.split_text(text)
        combined = " ".join(chunks)
        for word in words:
            assert word in combined, f"Word '{word}' missing from chunks"

    def test_empty_text_returns_empty(self):
        """Empty input should return an empty list or list with empty string."""
        splitter = make_splitter(chunk_size=1000, chunk_overlap=200)
        result = splitter.split_text("")
        # LangChain may return [] or [""]
        assert result == [] or result == [""]

"""
Unit tests for backend.utils.hashing.
Verifies SHA-256 determinism, correctness, and edge-case handling.
"""
import hashlib
from pathlib import Path

import pytest

from backend.utils.hashing import sha256_bytes, sha256_file, sha256_text


class TestSha256Bytes:
    """Tests for sha256_bytes()."""

    def test_known_value(self):
        """SHA-256 of b'' is the well-known empty-string hash."""
        expected = hashlib.sha256(b"").hexdigest()
        assert sha256_bytes(b"") == expected

    def test_deterministic(self):
        """Same input always produces the same digest."""
        data = b"hello, AURA"
        assert sha256_bytes(data) == sha256_bytes(data)

    def test_different_inputs_differ(self):
        """Different byte strings produce different digests."""
        assert sha256_bytes(b"aaa") != sha256_bytes(b"bbb")

    def test_output_length(self):
        """SHA-256 hex digest is always 64 characters."""
        assert len(sha256_bytes(b"test data")) == 64

    def test_output_is_hex(self):
        """Digest contains only hex characters."""
        digest = sha256_bytes(b"test")
        assert all(c in "0123456789abcdef" for c in digest)


class TestSha256Text:
    """Tests for sha256_text()."""

    def test_matches_manual_utf8_hash(self):
        """sha256_text should match manually encoding + hashing."""
        text = "Project AURA"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert sha256_text(text) == expected

    def test_deterministic(self):
        """Same text always returns the same hash."""
        t = "sovereign local node"
        assert sha256_text(t) == sha256_text(t)

    def test_different_texts_differ(self):
        """Different texts produce different hashes."""
        assert sha256_text("alpha") != sha256_text("beta")

    def test_custom_encoding(self):
        """latin-1 encoding produces different hash from utf-8 for non-ASCII."""
        text = "café"
        h_utf8 = sha256_text(text, encoding="utf-8")
        h_latin = sha256_text(text, encoding="latin-1")
        assert h_utf8 != h_latin


class TestSha256File:
    """Tests for sha256_file()."""

    def test_deterministic_across_calls(self, tmp_path):
        """Same file content hashes to the same value on repeated calls."""
        f = tmp_path / "file.txt"
        f.write_bytes(b"stable content")
        assert sha256_file(f) == sha256_file(f)

    def test_different_content_differs(self, tmp_path):
        """Two files with different content have different hashes."""
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_bytes(b"content A")
        b.write_bytes(b"content B")
        assert sha256_file(a) != sha256_file(b)

    def test_matches_bytes_hash(self, tmp_path):
        """sha256_file result matches sha256_bytes on the same raw bytes."""
        data = b"AURA document content"
        f = tmp_path / "doc.bin"
        f.write_bytes(data)
        assert sha256_file(f) == sha256_bytes(data)

    def test_missing_file_raises(self, tmp_path):
        """FileNotFoundError is raised for a non-existent file."""
        with pytest.raises(FileNotFoundError):
            sha256_file(tmp_path / "ghost.pdf")

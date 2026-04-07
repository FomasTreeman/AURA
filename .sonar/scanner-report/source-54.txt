"""
Unit tests for backend.database.chroma.
Tests ChromaDB client singleton and collection management.
"""

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest


class TestGetClient:
    """Tests for get_client()."""

    def test_returns_singleton(self):
        """get_client() should return the same instance on repeated calls."""
        with (
            patch("backend.database.chroma.chromadb") as mock_chroma,
            patch("backend.database.chroma.CHROMA_PATH", Path("/tmp/test_chroma")),
        ):
            mock_client = MagicMock()
            mock_chroma.PersistentClient.return_value = mock_client

            # Clear the module-level singleton
            import backend.database.chroma as chroma_module

            chroma_module._client = None

            result1 = chroma_module.get_client()
            result2 = chroma_module.get_client()

            assert result1 is result2

    def test_creates_persistent_client(self):
        """get_client() should create a PersistentClient with correct path."""
        with (
            patch("backend.database.chroma.chromadb") as mock_chroma,
            patch("backend.database.chroma.CHROMA_PATH", Path("/tmp/test_chroma")),
        ):
            mock_client = MagicMock()
            mock_chroma.PersistentClient.return_value = mock_client

            import backend.database.chroma as chroma_module

            chroma_module._client = None

            chroma_module.get_client()

            mock_chroma.PersistentClient.assert_called_once_with(
                path="/tmp/test_chroma"
            )

    def test_creates_parent_directories(self):
        """get_client() should create CHROMA_PATH parent directories."""
        with (
            patch("backend.database.chroma.chromadb") as mock_chroma,
            patch(
                "backend.database.chroma.CHROMA_PATH", Path("/tmp/aura_test/chroma_db")
            ),
        ):
            mock_client = MagicMock()
            mock_chroma.PersistentClient.return_value = mock_client

            import backend.database.chroma as chroma_module

            chroma_module._client = None

            chroma_module.get_client()

            assert Path("/tmp/aura_test/chroma_db").parent.exists()


class TestGetCollection:
    """Tests for get_collection()."""

    def test_returns_collection(self):
        """get_collection() should return a ChromaDB collection."""
        with (
            patch("backend.database.chroma.chromadb") as mock_chroma,
            patch("backend.database.chroma.CHROMA_PATH", Path("/tmp/test_chroma")),
            patch("backend.database.chroma.CHROMA_COLLECTION", "test_collection"),
        ):
            mock_client = MagicMock()
            mock_collection = MagicMock()
            mock_client.get_or_create_collection.return_value = mock_collection
            mock_chroma.PersistentClient.return_value = mock_client

            import backend.database.chroma as chroma_module

            chroma_module._client = None

            result = chroma_module.get_collection()

            assert result is mock_collection

    def test_creates_with_cosine_similarity(self):
        """get_collection() should create collection with cosine similarity."""
        with (
            patch("backend.database.chroma.chromadb") as mock_chroma,
            patch("backend.database.chroma.CHROMA_PATH", Path("/tmp/test_chroma")),
            patch("backend.database.chroma.CHROMA_COLLECTION", "test_collection"),
        ):
            mock_client = MagicMock()
            mock_chroma.PersistentClient.return_value = mock_client

            import backend.database.chroma as chroma_module

            chroma_module._client = None

            chroma_module.get_collection()

            mock_client.get_or_create_collection.assert_called_once()
            call_kwargs = mock_client.get_or_create_collection.call_args[1]
            assert call_kwargs["metadata"] == {"hnsw:space": "cosine"}


class TestResetCollection:
    """Tests for reset_collection()."""

    def test_deletes_existing_collection(self):
        """reset_collection() should delete the existing collection first."""
        with (
            patch("backend.database.chroma.chromadb") as mock_chroma,
            patch("backend.database.chroma.CHROMA_PATH", Path("/tmp/test_chroma")),
            patch("backend.database.chroma.CHROMA_COLLECTION", "test_collection"),
        ):
            mock_client = MagicMock()
            mock_client.get_or_create_collection.return_value = MagicMock()
            mock_chroma.PersistentClient.return_value = mock_client

            import backend.database.chroma as chroma_module

            chroma_module._client = None

            chroma_module.reset_collection()

            mock_client.delete_collection.assert_called_once_with("test_collection")

    def test_returns_fresh_collection(self):
        """reset_collection() should return a fresh empty collection."""
        with (
            patch("backend.database.chroma.chromadb") as mock_chroma,
            patch("backend.database.chroma.CHROMA_PATH", Path("/tmp/test_chroma")),
            patch("backend.database.chroma.CHROMA_COLLECTION", "test_collection"),
        ):
            mock_client = MagicMock()
            mock_collection = MagicMock()
            mock_client.get_or_create_collection.return_value = mock_collection
            mock_chroma.PersistentClient.return_value = mock_client

            import backend.database.chroma as chroma_module

            chroma_module._client = None

            result = chroma_module.reset_collection()

            assert result is mock_collection
            assert mock_client.delete_collection.call_count == 1
            assert mock_client.get_or_create_collection.call_count == 1

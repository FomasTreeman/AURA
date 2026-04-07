"""
Unit tests for backend.config.
Tests configuration loading, environment variable resolution, and path handling.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest


class TestGetHelper:
    """Tests for _get() helper function."""

    def test_returns_default_when_env_missing(self):
        """_get() should return default when env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            from backend.config import _get

            result = _get("NONEXISTENT_VAR_12345", "default_value")
            assert result == "default_value"

    def test_returns_env_value_when_set(self):
        """_get() should return env value when set."""
        with patch.dict(os.environ, {"TEST_VAR": "from_env"}):
            from backend.config import _get

            result = _get("TEST_VAR", "default")
            assert result == "from_env"

    def test_empty_string_returns_empty(self):
        """_get() should return empty string if env var is set to empty."""
        with patch.dict(os.environ, {"EMPTY_VAR": ""}):
            from backend.config import _get

            result = _get("EMPTY_VAR", "default")
            assert result == ""


class TestResolvePathHelper:
    """Tests for _resolve_path() helper function."""

    def test_absolute_path_unchanged(self):
        """Absolute paths should be returned unchanged."""
        from backend.config import _resolve_path

        result = _resolve_path("/absolute/path/to/file")
        assert result == Path("/absolute/path/to/file")

    def test_relative_path_resolved_to_project_root(self):
        """Relative paths should be resolved to project root."""
        from backend.config import _resolve_path, _PROJECT_ROOT

        result = _resolve_path("./relative/path")
        result_str = str(result)
        project_root_str = str(_PROJECT_ROOT)
        assert result.parent == _PROJECT_ROOT or project_root_str in result_str

    def test_resolve_path_returns_path_object(self):
        """_resolve_path() should return a Path object."""
        from backend.config import _resolve_path

        result = _resolve_path("some/path")
        assert isinstance(result, Path)


class TestConfigConstants:
    """Tests for configuration constants."""

    def test_ollama_defaults_exist(self):
        """OLLAMA_MODEL and OLLAMA_BASE_URL should be defined."""
        from backend.config import OLLAMA_MODEL, OLLAMA_BASE_URL

        assert OLLAMA_MODEL
        assert OLLAMA_BASE_URL
        assert isinstance(OLLAMA_MODEL, str)
        assert isinstance(OLLAMA_BASE_URL, str)

    def test_chroma_collection_name(self):
        """CHROMA_COLLECTION should be 'aura_documents'."""
        from backend.config import CHROMA_COLLECTION

        assert CHROMA_COLLECTION == "aura_documents"

    def test_retrieval_defaults(self):
        """RETRIEVAL_TOP_K and RETRIEVAL_SCORE_THRESHOLD should have sensible defaults."""
        from backend.config import RETRIEVAL_TOP_K, RETRIEVAL_SCORE_THRESHOLD

        assert RETRIEVAL_TOP_K > 0
        assert 0 <= RETRIEVAL_SCORE_THRESHOLD <= 1

    def test_federated_defaults(self):
        """Federated RAG config should have reasonable defaults."""
        from backend.config import (
            FEDERATED_TIMEOUT,
            FEDERATED_QUORUM,
            FEDERATED_MAX_RESPONSES,
            FEDERATED_TOP_K,
            RRF_K,
        )

        assert FEDERATED_TIMEOUT > 0
        assert FEDERATED_QUORUM >= 1
        assert FEDERATED_MAX_RESPONSES > 0
        assert FEDERATED_TOP_K > 0
        assert RRF_K > 0

    def test_p2p_config(self):
        """P2P config should have valid values."""
        from backend.config import P2P_HOST, P2P_PORT, P2P_MDNS_ENABLED

        assert P2P_HOST in ("0.0.0.0", "127.0.0.1", "localhost")
        assert isinstance(P2P_PORT, int)
        assert P2P_PORT > 0
        assert isinstance(P2P_MDNS_ENABLED, bool)

    def test_p2p_bootstrap_is_list(self):
        """P2P_BOOTSTRAP should be a list."""
        from backend.config import P2P_BOOTSTRAP

        assert isinstance(P2P_BOOTSTRAP, list)

    def test_query_topic_format(self):
        """AURA_QUERY_TOPIC should be a valid topic string."""
        from backend.config import AURA_QUERY_TOPIC

        assert AURA_QUERY_TOPIC.startswith("/aura/")
        assert "1.0.0" in AURA_QUERY_TOPIC

    def test_nonce_ttl_reasonable(self):
        """NONCE_TTL should be a reasonable value (seconds)."""
        from backend.config import NONCE_TTL

        assert NONCE_TTL > 0
        assert NONCE_TTL < 86400  # Less than 24 hours

    def test_batch_size_defined(self):
        """BATCH_SIZE should be defined for ingestion."""
        from backend.config import BATCH_SIZE

        assert BATCH_SIZE > 0
        assert BATCH_SIZE <= 100  # Shouldn't be too large

    def test_chunk_size_config(self):
        """MAX_CHUNK_SIZE and CHUNK_OVERLAP should be defined."""
        from backend.config import MAX_CHUNK_SIZE, CHUNK_OVERLAP

        assert MAX_CHUNK_SIZE > 0
        assert CHUNK_OVERLAP >= 0
        assert CHUNK_OVERLAP < MAX_CHUNK_SIZE  # Overlap should be less than chunk size

    def test_embedding_model_defined(self):
        """EMBEDDING_MODEL should be defined."""
        from backend.config import EMBEDDING_MODEL

        assert EMBEDDING_MODEL
        assert isinstance(EMBEDDING_MODEL, str)

    def test_chroma_path_is_path(self):
        """CHROMA_PATH should be a Path object."""
        from backend.config import CHROMA_PATH

        assert isinstance(CHROMA_PATH, Path)

    def test_ingest_dir_is_path(self):
        """INGEST_DIR should be a Path object."""
        from backend.config import INGEST_DIR

        assert isinstance(INGEST_DIR, Path)

    def test_p2p_key_dir_is_path(self):
        """P2P_KEY_DIR should be a Path object."""
        from backend.config import P2P_KEY_DIR

        assert isinstance(P2P_KEY_DIR, Path)


class TestConfigWithEnvOverrides:
    """Tests for config behavior with environment variable overrides."""

    def test_ollama_model_from_env(self):
        """OLLAMA_MODEL can be overridden via environment."""
        with patch.dict(os.environ, {"OLLAMA_MODEL": "custom-model:v1"}):
            # Need to reload the module to pick up env changes
            import importlib
            import backend.config

            importlib.reload(backend.config)
            assert backend.config.OLLAMA_MODEL == "custom-model:v1"

    def test_p2p_port_from_env(self):
        """P2P_PORT can be overridden via environment."""
        with patch.dict(os.environ, {"P2P_PORT": "9999"}):
            import importlib
            import backend.config

            importlib.reload(backend.config)
            assert backend.config.P2P_PORT == 9999

    def test_chroma_path_from_env(self):
        """CHROMA_PATH can be overridden via environment."""
        with patch.dict(os.environ, {"CHROMA_PATH": "/custom/path/db"}):
            import importlib
            import backend.config

            importlib.reload(backend.config)
            assert "/custom/path/db" in str(backend.config.CHROMA_PATH)

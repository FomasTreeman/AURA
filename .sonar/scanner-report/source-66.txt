"""
Unit tests for backend.database.history.
Tests SQLite persistence for chat history.
"""

import json
import sqlite3
import time
import importlib
from pathlib import Path

import pytest


class MockSession:
    """Mock QuerySession for testing."""

    def __init__(
        self,
        query_id="test-123",
        question="What is AURA?",
        sources=None,
        federation_info=None,
        started_at=None,
        error=None,
    ):
        self.query_id = query_id
        self.question = question
        self.sources = sources or []
        self.federation_info = federation_info
        self.started_at = started_at or time.time()
        self.error = error


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Create a test database with isolated path."""
    db_dir = tmp_path / "test_data"
    db_dir.mkdir(parents=True, exist_ok=True)

    test_chroma_path = db_dir / "chroma_db"

    monkeypatch.setattr("backend.database.history.CHROMA_PATH", test_chroma_path)

    import backend.database.history as hist_module

    importlib.reload(hist_module)

    hist_module.init_db()

    return hist_module, db_dir / "chat_history.db"


class TestInitDb:
    """Tests for init_db()."""

    def test_init_creates_table(self, test_db):
        """init_db() should create the chat_history table."""
        hist_module, _ = test_db
        # Table creation is verified by init_db not raising
        # We verify by attempting to use the API which would fail if table doesn't exist
        session = MockSession(query_id="verify-table")
        hist_module.save_session(session, "Answer", 100.0)
        result = hist_module.get_session("verify-table")
        assert result is not None

    def test_init_is_idempotent(self, test_db):
        """init_db() called twice should not raise."""
        hist_module, _ = test_db
        hist_module.init_db()  # Should not raise


class TestSaveSession:
    """Tests for save_session()."""

    def test_save_session_inserts_row(self, test_db):
        """save_session() should insert a row into the database."""
        hist_module, db_path = test_db

        session = MockSession(
            query_id="save-test-001",
            question="Test question",
            sources=[{"text": "Test source"}],
        )
        hist_module.save_session(session, "Test answer", 100.0)

        result = hist_module.get_session("save-test-001")
        assert result is not None
        assert result["question"] == "Test question"
        assert result["answer"] == "Test answer"

    def test_save_session_with_error(self, test_db):
        """save_session() should store error field."""
        hist_module, _ = test_db

        session = MockSession(
            query_id="error-test",
            question="Query",
            error="Ollama connection failed",
        )
        hist_module.save_session(session, "", 0.0)

        result = hist_module.get_session("error-test")
        assert result is not None
        assert result["error"] == "Ollama connection failed"

    def test_save_session_replaces_on_conflict(self, test_db):
        """save_session() with existing query_id should update."""
        hist_module, _ = test_db

        session = MockSession(query_id="replace-test", question="Original")
        hist_module.save_session(session, "Original answer", 100.0)

        session2 = MockSession(query_id="replace-test", question="Updated")
        hist_module.save_session(session2, "Updated answer", 200.0)

        result = hist_module.get_session("replace-test")
        assert result is not None
        assert result["answer"] == "Updated answer"


class TestGetSession:
    """Tests for get_session()."""

    def test_get_session_returns_full_data(self, test_db):
        """get_session() should return complete session."""
        hist_module, _ = test_db

        session = MockSession(
            query_id="session-001",
            question="What is the capital of France?",
            sources=[{"text": "Paris is the capital.", "source": "geo.txt"}],
        )
        hist_module.save_session(session, "Paris.", 150.5)

        result = hist_module.get_session("session-001")
        assert result is not None
        assert result["question"] == "What is the capital of France?"

    def test_get_session_not_found_returns_none(self, test_db):
        """get_session() for non-existent ID should return None."""
        hist_module, _ = test_db
        result = hist_module.get_session("nonexistent-id")
        assert result is None


class TestListSessions:
    """Tests for list_sessions()."""

    def test_list_sessions_empty_database(self, test_db):
        """list_sessions() on empty DB should return empty list."""
        hist_module, _ = test_db
        results = hist_module.list_sessions()
        assert results == []

    def test_list_sessions_returns_sessions(self, test_db):
        """list_sessions() should return sessions."""
        hist_module, _ = test_db

        session = MockSession(query_id="s1", question="Q1")
        hist_module.save_session(session, "A1", 100.0)

        session2 = MockSession(query_id="s2", question="Q2")
        hist_module.save_session(session2, "A2", 200.0)

        results = hist_module.list_sessions()
        assert len(results) == 2

    def test_list_sessions_respects_limit(self, test_db):
        """list_sessions(limit=N) should return at most N results."""
        hist_module, _ = test_db

        for i in range(5):
            session = MockSession(query_id=f"s{i}", question=f"Q{i}")
            hist_module.save_session(session, f"A{i}", 100.0)

        results = hist_module.list_sessions(limit=2)
        assert len(results) == 2

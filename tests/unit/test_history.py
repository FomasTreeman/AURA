"""
Unit tests for backend.database.history.
Tests SQLite persistence for chat history.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.database.history import (
    init_db,
    save_session,
    list_sessions,
    get_session,
)


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
def mock_db_path(tmp_path, monkeypatch):
    """Use a temp directory for the test database."""
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    # Patch CHROMA_PATH so _DB_PATH points to our temp dir
    monkeypatch.setattr("backend.database.history.CHROMA_PATH", db_dir / "chroma_db")
    # Re-import to pick up patched config
    import importlib
    import backend.database.history as hist

    importlib.reload(hist)
    return db_dir / "chat_history.db"


@pytest.fixture
def populated_db(mock_db_path):
    """Initialize DB with test data."""
    import backend.database.history as hist

    hist.init_db()

    # Insert a test session
    session = MockSession(
        query_id="session-001",
        question="What is the capital of France?",
        sources=[{"text": "Paris is the capital.", "source": "geo.txt"}],
        federation_info={"local_count": 1, "peer_count": 0},
    )
    hist.save_session(session, "Paris.", 150.5)

    # Insert another session
    session2 = MockSession(
        query_id="session-002",
        question="Explain quantum computing",
        sources=[{"text": "Quantum computing uses qubits.", "source": "qc.txt"}],
    )
    hist.save_session(session2, "Quantum computing explanation...", 250.0)

    return hist


class TestInitDb:
    """Tests for init_db()."""

    def test_init_creates_table(self, mock_db_path):
        """init_db() should create the chat_history table."""
        import backend.database.history as hist

        hist.init_db()

        # Verify table exists
        import sqlite3

        conn = sqlite3.connect(mock_db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_history'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_init_is_idempotent(self, mock_db_path):
        """Calling init_db() twice should not raise."""
        import backend.database.history as hist

        hist.init_db()
        hist.init_db()  # Should not raise


class TestSaveSession:
    """Tests for save_session()."""

    def test_save_session_inserts_row(self, mock_db_path):
        """save_session() should insert a row into the database."""
        import backend.database.history as hist

        hist.init_db()

        session = MockSession(
            query_id="save-test-001",
            question="Test question",
            sources=[{"text": "Test source"}],
        )
        hist.save_session(session, "Test answer", 100.0)

        # Verify the row was inserted
        result = hist.get_session("save-test-001")
        assert result is not None
        assert result["question"] == "Test question"
        assert result["answer"] == "Test answer"
        assert result["duration_ms"] == 100.0

    def test_save_session_with_federation_info(self, mock_db_path):
        """save_session() should store federation_info as JSON."""
        import backend.database.history as hist

        hist.init_db()

        session = MockSession(
            query_id="federation-test",
            question="Query",
            federation_info={"peers_responded": ["peer1", "peer2"]},
        )
        hist.save_session(session, "Answer", 50.0)

        result = hist.get_session("federation-test")
        assert result is not None
        assert result["federation_info"]["peers_responded"] == ["peer1", "peer2"]

    def test_save_session_with_error(self, mock_db_path):
        """save_session() should store error field."""
        import backend.database.history as hist

        hist.init_db()

        session = MockSession(
            query_id="error-test",
            question="Query",
            error="Ollama connection failed",
        )
        hist.save_session(session, "", 0.0)

        result = hist.get_session("error-test")
        assert result is not None
        assert result["error"] == "Ollama connection failed"

    def test_save_session_replaces_on_conflict(self, mock_db_path):
        """save_session() with existing query_id should update (REPLACE)."""
        import backend.database.history as hist

        hist.init_db()

        session = MockSession(query_id="replace-test", question="Original")
        hist.save_session(session, "Original answer", 100.0)

        # Update with same query_id
        session2 = MockSession(query_id="replace-test", question="Updated")
        hist.save_session(session2, "Updated answer", 200.0)

        result = hist.get_session("replace-test")
        assert result is not None
        assert result["answer"] == "Updated answer"
        assert result["duration_ms"] == 200.0


class TestListSessions:
    """Tests for list_sessions()."""

    def test_list_sessions_returns_newest_first(self, populated_db):
        """list_sessions() should return sessions in descending order by time."""
        results = populated_db.list_sessions()
        assert len(results) == 2
        # session-002 was created after session-001
        assert results[0]["query_id"] == "session-002"
        assert results[1]["query_id"] == "session-001"

    def test_list_sessions_respects_limit(self, populated_db):
        """list_sessions(limit=N) should return at most N results."""
        results = populated_db.list_sessions(limit=1)
        assert len(results) == 1
        assert results[0]["query_id"] == "session-002"  # Newest

    def test_list_sessions_default_limit(self, populated_db):
        """list_sessions() with no limit should use default (50)."""
        results = populated_db.list_sessions()
        # We only have 2 sessions
        assert len(results) == 2

    def test_list_sessions_answer_preview_truncation(self, populated_db):
        """Long answers should be truncated to 200 chars with '...'."""
        results = populated_db.list_sessions()
        for r in results:
            assert len(r["answer_preview"]) <= 203  # 200 + "..."

    def test_list_sessions_sources_count(self, populated_db):
        """list_sessions() should include sources_count."""
        results = populated_db.list_sessions()
        for r in results:
            assert "sources_count" in r
            assert isinstance(r["sources_count"], int)

    def test_empty_database_returns_empty_list(self, mock_db_path):
        """list_sessions() on empty DB should return empty list."""
        import backend.database.history as hist

        hist.init_db()
        results = hist.list_sessions()
        assert results == []


class TestGetSession:
    """Tests for get_session()."""

    def test_get_session_returns_full_data(self, populated_db):
        """get_session() should return complete session with sources."""
        result = populated_db.get_session("session-001")
        assert result is not None
        assert result["query_id"] == "session-001"
        assert result["question"] == "What is the capital of France?"
        assert result["answer"] == "Paris."
        assert result["sources"] == [
            {"text": "Paris is the capital.", "source": "geo.txt"}
        ]

    def test_get_session_with_federation_info(self, populated_db):
        """get_session() should include federation_info."""
        result = populated_db.get_session("session-001")
        assert result["federation_info"] == {"local_count": 1, "peer_count": 0}

    def test_get_session_not_found_returns_none(self, populated_db):
        """get_session() for non-existent ID should return None."""
        result = populated_db.get_session("nonexistent-id")
        assert result is None

    def test_get_session_includes_duration_and_started_at(self, populated_db):
        """get_session() should include timing fields."""
        result = populated_db.get_session("session-001")
        assert result["duration_ms"] == 150.5
        assert result["started_at"] > 0

"""
Unit tests for backend.api.sse.
Covers: SSE formatting, session management, NDJSON→SSE conversion, stream_query_sse.
"""
import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.sse import (
    QuerySession,
    _format_sse,
    _sessions,
    _wrap_ndjson_to_sse,
    cleanup_old_sessions,
    create_query_session,
    get_query_session,
    stream_query_sse,
)


# ── _format_sse ───────────────────────────────────────────────────────────────

class TestFormatSSE:
    def test_correct_format(self):
        result = _format_sse("token", {"token": "hello"})
        assert result == 'event: token\ndata: {"token": "hello"}\n\n'

    def test_event_name_in_output(self):
        result = _format_sse("done", {"query_id": "abc"})
        assert result.startswith("event: done\n")

    def test_data_is_valid_json(self):
        result = _format_sse("sources", {"sources": [1, 2, 3]})
        data_line = [line for line in result.split("\n") if line.startswith("data:")][0]
        parsed = json.loads(data_line[len("data: "):])
        assert parsed["sources"] == [1, 2, 3]

    def test_ends_with_double_newline(self):
        result = _format_sse("ping", {})
        assert result.endswith("\n\n")

    def test_unicode_preserved(self):
        result = _format_sse("token", {"token": "héllo wörld"})
        assert "héllo wörld" in result


# ── Session management ────────────────────────────────────────────────────────

class TestSessionManagement:
    def setup_method(self):
        _sessions.clear()

    def teardown_method(self):
        _sessions.clear()

    def test_create_returns_string_id(self):
        qid = create_query_session("what is AURA?")
        assert isinstance(qid, str)
        assert len(qid) > 0

    def test_create_stores_question(self):
        qid = create_query_session("test question")
        session = _sessions[qid]
        assert session.question == "test question"

    def test_create_unique_ids(self):
        ids = {create_query_session("q") for _ in range(10)}
        assert len(ids) == 10

    def test_get_returns_session(self):
        qid = create_query_session("hello")
        session = get_query_session(qid)
        assert session is not None
        assert session.query_id == qid

    def test_get_unknown_id_returns_none(self):
        assert get_query_session("does-not-exist") is None

    def test_session_initial_state(self):
        qid = create_query_session("question?")
        session = _sessions[qid]
        assert session.tokens == []
        assert session.sources == []
        assert session.completed is False
        assert session.error is None
        assert session.federation_info is None


class TestCleanupOldSessions:
    def setup_method(self):
        _sessions.clear()

    def teardown_method(self):
        _sessions.clear()

    def test_removes_old_sessions(self):
        qid = create_query_session("old query")
        _sessions[qid].started_at = time.time() - 7200  # 2h ago
        cleanup_old_sessions(max_age_seconds=3600)
        assert qid not in _sessions

    def test_keeps_recent_sessions(self):
        qid = create_query_session("recent query")
        cleanup_old_sessions(max_age_seconds=3600)
        assert qid in _sessions

    def test_mixed_ages(self):
        old_qid = create_query_session("old")
        _sessions[old_qid].started_at = time.time() - 7200
        new_qid = create_query_session("new")
        cleanup_old_sessions(max_age_seconds=3600)
        assert old_qid not in _sessions
        assert new_qid in _sessions


# ── _wrap_ndjson_to_sse ───────────────────────────────────────────────────────

async def _lines(*lines):
    """Helper: async generator yielding given lines."""
    for line in lines:
        yield line


class TestWrapNdjsonToSse:
    @pytest.mark.asyncio
    async def test_token_becomes_token_event(self):
        ndjson = _lines('{"token": "hello"}\n')
        events = [e async for e in _wrap_ndjson_to_sse(ndjson, "qid1")]
        assert any("event: token" in e for e in events)

    @pytest.mark.asyncio
    async def test_done_with_sources_emits_sources_event(self):
        ndjson = _lines('{"done": true, "sources": [{"source": "doc.pdf"}]}\n')
        events = [e async for e in _wrap_ndjson_to_sse(ndjson, "qid1")]
        assert any("event: sources" in e for e in events)

    @pytest.mark.asyncio
    async def test_federation_becomes_federation_event(self):
        ndjson = _lines('{"federation": {"peer_count": 2}}\n')
        events = [e async for e in _wrap_ndjson_to_sse(ndjson, "qid1")]
        assert any("event: federation" in e for e in events)

    @pytest.mark.asyncio
    async def test_error_becomes_error_event(self):
        ndjson = _lines('{"error": "something broke"}\n')
        events = [e async for e in _wrap_ndjson_to_sse(ndjson, "qid1")]
        assert any("event: error" in e for e in events)

    @pytest.mark.asyncio
    async def test_empty_lines_skipped(self):
        ndjson = _lines("", "  ", '{"token": "hi"}\n')
        events = [e async for e in _wrap_ndjson_to_sse(ndjson, "qid1")]
        # Only one event (the token), empty lines produce nothing
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_invalid_json_skipped(self):
        ndjson = _lines("not json\n", '{"token": "ok"}\n')
        events = [e async for e in _wrap_ndjson_to_sse(ndjson, "qid1")]
        assert len(events) == 1
        assert "event: token" in events[0]

    @pytest.mark.asyncio
    async def test_token_data_preserved(self):
        ndjson = _lines('{"token": "world"}\n')
        events = [e async for e in _wrap_ndjson_to_sse(ndjson, "qid1")]
        data = json.loads(events[0].split("data: ", 1)[1].strip())
        assert data["token"] == "world"


# ── stream_query_sse ──────────────────────────────────────────────────────────

class TestStreamQuerySse:
    def setup_method(self):
        _sessions.clear()

    def teardown_method(self):
        _sessions.clear()

    def _make_mock_generator(self, tokens=("Hello", " world"), sources=None):
        """Return an async generator factory that mimics federated_stream_answer."""
        if sources is None:
            sources = [{"source": "doc.pdf", "page": 1, "cid": "abc123", "text": "snippet", "score": 0.9}]

        async def gen(question, retriever):
            for t in tokens:
                yield json.dumps({"token": t}) + "\n"
            yield json.dumps({"done": True, "sources": sources}) + "\n"

        return gen

    @pytest.mark.asyncio
    async def test_emits_token_events(self):
        with patch("backend.rag.generator.federated_stream_answer", self._make_mock_generator()), \
             patch("backend.api.sse.estimate_query_carbon", return_value=0.001), \
             patch("backend.database.history.save_session"):
            events = [e async for e in stream_query_sse("test?")]
        assert any("event: token" in e for e in events)

    @pytest.mark.asyncio
    async def test_emits_sources_event(self):
        with patch("backend.rag.generator.federated_stream_answer", self._make_mock_generator()), \
             patch("backend.api.sse.estimate_query_carbon", return_value=0.001), \
             patch("backend.database.history.save_session"):
            events = [e async for e in stream_query_sse("test?")]
        assert any("event: sources" in e for e in events)

    @pytest.mark.asyncio
    async def test_emits_done_event_with_query_id(self):
        with patch("backend.rag.generator.federated_stream_answer", self._make_mock_generator()), \
             patch("backend.api.sse.estimate_query_carbon", return_value=0.001), \
             patch("backend.database.history.save_session"):
            events = [e async for e in stream_query_sse("test?")]
        done_events = [e for e in events if "event: done" in e]
        assert len(done_events) == 1
        data = json.loads(done_events[0].split("data: ", 1)[1].strip())
        assert "query_id" in data
        assert "duration_ms" in data

    @pytest.mark.asyncio
    async def test_session_marked_completed(self):
        _sessions.clear()
        with patch("backend.rag.generator.federated_stream_answer", self._make_mock_generator()), \
             patch("backend.api.sse.estimate_query_carbon", return_value=0.001), \
             patch("backend.database.history.save_session"):
            events = [e async for e in stream_query_sse("test?")]
        # At least one session should be completed
        assert any(s.completed for s in _sessions.values())

    @pytest.mark.asyncio
    async def test_tokens_accumulated_in_session(self):
        _sessions.clear()
        with patch("backend.rag.generator.federated_stream_answer", self._make_mock_generator(["Hi", " there"])), \
             patch("backend.api.sse.estimate_query_carbon", return_value=0.001), \
             patch("backend.database.history.save_session"):
            events = [e async for e in stream_query_sse("test?")]
        session = next(iter(_sessions.values()))
        assert "Hi" in session.tokens
        assert " there" in session.tokens

    @pytest.mark.asyncio
    async def test_generator_error_emits_error_event(self):
        async def failing_gen(question, retriever):
            raise RuntimeError("LLM exploded")
            yield  # make it a generator

        with patch("backend.rag.generator.federated_stream_answer", failing_gen), \
             patch("backend.api.sse.estimate_query_carbon", return_value=0.001):
            events = [e async for e in stream_query_sse("test?")]
        assert any("event: error" in e for e in events)

    @pytest.mark.asyncio
    async def test_save_session_called_on_completion(self):
        with patch("backend.rag.generator.federated_stream_answer", self._make_mock_generator()), \
             patch("backend.api.sse.estimate_query_carbon", return_value=0.001), \
             patch("backend.database.history.save_session") as mock_save:
            events = [e async for e in stream_query_sse("test?")]
        mock_save.assert_called_once()

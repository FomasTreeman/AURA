"""
Server-Sent Events (SSE) streaming for AURA.

Provides real-time streaming of:
- Query responses (LLM tokens + citations)
- Peer status updates
- System metrics
"""

import asyncio
import json
import time
import uuid
from typing import AsyncGenerator, Optional
from dataclasses import dataclass, field

from backend.observability.metrics import OBSERVABILITY_METRICS
from backend.observability.greenops import estimate_query_carbon
from backend.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class QuerySession:
    """Tracks an active query session."""

    query_id: str
    question: str
    started_at: float = field(default_factory=time.time)
    tokens: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    federation_info: Optional[dict] = None
    completed: bool = False
    error: Optional[str] = None


# Active query sessions (in production, use Redis or similar)
_sessions: dict[str, QuerySession] = {}


def create_query_session(question: str) -> str:
    """Create a new query session and return its ID."""
    query_id = str(uuid.uuid4())
    _sessions[query_id] = QuerySession(query_id=query_id, question=question)
    return query_id


def get_query_session(query_id: str) -> Optional[QuerySession]:
    """Get a query session by ID."""
    return _sessions.get(query_id)


def cleanup_old_sessions(max_age_seconds: float = 3600):
    """Remove sessions older than max_age_seconds."""
    now = time.time()
    to_remove = [
        qid
        for qid, session in _sessions.items()
        if now - session.started_at > max_age_seconds
    ]
    for qid in to_remove:
        del _sessions[qid]


async def stream_query_sse(
    question: str,
    federated_retriever=None,
) -> AsyncGenerator[str, None]:
    """
    Stream a RAG query response as Server-Sent Events.

    Yields SSE-formatted events:
    - event: federation
      data: {"local_count": ..., "peer_count": ..., ...}

    - event: token
      data: {"token": "..."}

    - event: sources
      data: {"sources": [...]}

    - event: done
      data: {"query_id": "...", "duration_ms": ...}

    - event: error
      data: {"error": "..."}
    """
    query_id = create_query_session(question)
    session = _sessions[query_id]
    start_time = time.time()

    try:
        # Import here to avoid circular imports
        from backend.rag.generator import federated_stream_answer

        async for line in _wrap_ndjson_to_sse(
            federated_stream_answer(question, federated_retriever), query_id
        ):
            yield line

            # Accumulate tokens and sources for persistence
            try:
                if "\ndata: " in line:
                    event_part, data_part = line.split("\ndata: ", 1)
                    data = json.loads(data_part.strip())
                    if "event: token" in event_part:
                        session.tokens.append(data.get("token", ""))
                    elif "event: sources" in event_part:
                        session.sources = data.get("sources", [])
                    elif "event: federation" in event_part:
                        session.federation_info = data
            except Exception:
                pass

        # Record metrics
        duration = time.time() - start_time
        OBSERVABILITY_METRICS.record_query(duration, success=True)

        # Estimate and record carbon
        carbon = estimate_query_carbon(duration, used_gpu=False)
        OBSERVABILITY_METRICS.record_carbon(carbon)

        # Send completion event
        yield _format_sse(
            "done",
            {
                "query_id": query_id,
                "duration_ms": duration * 1000,
                "carbon_grams": carbon,
            },
        )

        session.completed = True

        # Persist to SQLite
        try:
            from backend.database.history import save_session

            save_session(session, "".join(session.tokens), duration * 1000)
        except Exception as exc:
            log.warning("Failed to persist chat session: %s", exc)

    except Exception as e:
        log.error("Query stream error: %s", e)
        duration = time.time() - start_time
        OBSERVABILITY_METRICS.record_query(duration, success=False)
        session.error = str(e)

        yield _format_sse("error", {"error": str(e), "query_id": query_id})


async def _wrap_ndjson_to_sse(
    ndjson_gen: AsyncGenerator,
    query_id: str,
) -> AsyncGenerator[str, None]:
    """
    Convert the existing NDJSON stream to SSE format.
    """
    try:
        async for line in ndjson_gen:
            if not line or not line.strip():
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Map NDJSON events to SSE events
            if "federation" in data:
                yield _format_sse("federation", data["federation"])
            elif "token" in data:
                yield _format_sse("token", {"token": data["token"]})
            elif "done" in data and data.get("done"):
                if "sources" in data:
                    yield _format_sse("sources", {"sources": data["sources"]})
            elif "error" in data:
                yield _format_sse("error", {"error": data["error"]})
    except Exception as e:
        log.error("Error converting NDJSON to SSE: %s", e)
        yield _format_sse("error", {"error": str(e)})


def _format_sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    json_data = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {json_data}\n\n"


async def stream_peer_updates(
    adapter,
    interval: float = 5.0,
) -> AsyncGenerator[str, None]:
    """
    Stream peer status updates as SSE.

    Yields updates every `interval` seconds with current peer list and latency.
    """
    while True:
        try:
            if adapter is None:
                yield _format_sse(
                    "peers",
                    {
                        "running": False,
                        "peers": [],
                        "timestamp": time.time(),
                    },
                )
            else:
                peers = []
                for p in adapter.get_peers():
                    peers.append(
                        {
                            "peer_id": p.peer_id[:16] + "...",
                            "peer_id_full": p.peer_id,
                            "multiaddrs": p.multiaddrs,
                            "latency_ms": None,  # TODO: implement ping
                        }
                    )

                yield _format_sse(
                    "peers",
                    {
                        "running": True,
                        "peer_id": adapter.peer_id,
                        "peer_count": len(peers),
                        "peers": peers,
                        "timestamp": time.time(),
                    },
                )

            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Peer stream error: %s", e)
            yield _format_sse("error", {"error": str(e)})
            await asyncio.sleep(interval)


async def stream_metrics_updates(
    interval: float = 10.0,
) -> AsyncGenerator[str, None]:
    """
    Stream system metrics updates as SSE.

    Yields updates every `interval` seconds.
    """
    while True:
        try:
            OBSERVABILITY_METRICS.update_system_metrics()

            yield _format_sse(
                "metrics",
                {
                    "queries_total": OBSERVABILITY_METRICS.queries_total.value,
                    "queries_successful": OBSERVABILITY_METRICS.queries_successful.value,
                    "queries_failed": OBSERVABILITY_METRICS.queries_failed.value,
                    "peers_connected": OBSERVABILITY_METRICS.peers_connected.value,
                    "cpu_usage_percent": OBSERVABILITY_METRICS.cpu_usage_percent.value,
                    "memory_usage_bytes": OBSERVABILITY_METRICS.memory_usage_bytes.value,
                    "carbon_estimate_grams": OBSERVABILITY_METRICS.carbon_estimate_grams.value,
                    "grid_intensity_gco2_kwh": OBSERVABILITY_METRICS.grid_intensity_gco2_kwh.value,
                    "uptime_seconds": time.time() - OBSERVABILITY_METRICS._start_time,
                    "timestamp": time.time(),
                },
            )

            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Metrics stream error: %s", e)
            yield _format_sse("error", {"error": str(e)})
            await asyncio.sleep(interval)

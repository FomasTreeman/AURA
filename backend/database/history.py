"""
SQLite persistence for chat history.
Stores completed QuerySession data so the frontend can display past queries.
"""
import json
import sqlite3
from typing import Optional

from backend.config import CHROMA_PATH

# Sibling to the chroma_db folder
_DB_PATH = CHROMA_PATH.parent / "chat_history.db"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the chat_history table if it does not already exist."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                query_id       TEXT PRIMARY KEY,
                question       TEXT NOT NULL,
                answer         TEXT NOT NULL,
                sources        TEXT NOT NULL,
                federation_info TEXT,
                started_at     REAL NOT NULL,
                duration_ms    REAL NOT NULL,
                error          TEXT
            )
        """)


def save_session(session, answer: str, duration_ms: float) -> None:
    """Persist a completed QuerySession to SQLite."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO chat_history
            (query_id, question, answer, sources, federation_info, started_at, duration_ms, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.query_id,
                session.question,
                answer,
                json.dumps(session.sources),
                json.dumps(session.federation_info) if session.federation_info else None,
                session.started_at,
                duration_ms,
                session.error,
            ),
        )


def list_sessions(limit: int = 50) -> list[dict]:
    """Return the most recent sessions, newest first, with a short answer preview."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT query_id, question, answer, sources, started_at, duration_ms, error
            FROM chat_history
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result = []
    for r in rows:
        answer = r["answer"]
        sources = json.loads(r["sources"])
        result.append({
            "query_id": r["query_id"],
            "question": r["question"],
            "answer_preview": answer[:200] + ("..." if len(answer) > 200 else ""),
            "sources_count": len(sources),
            "started_at": r["started_at"],
            "duration_ms": r["duration_ms"],
            "error": r["error"],
        })
    return result


def get_session(query_id: str) -> Optional[dict]:
    """Return a single session with full answer text and sources."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM chat_history WHERE query_id = ?", (query_id,)
        ).fetchone()

    if row is None:
        return None
    return {
        "query_id": row["query_id"],
        "question": row["question"],
        "answer": row["answer"],
        "sources": json.loads(row["sources"]),
        "federation_info": json.loads(row["federation_info"]) if row["federation_info"] else None,
        "started_at": row["started_at"],
        "duration_ms": row["duration_ms"],
        "error": row["error"],
    }

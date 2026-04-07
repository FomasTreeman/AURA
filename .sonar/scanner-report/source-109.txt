"""
LLM generation module for AURA RAG pipeline.
Uses Ollama (via langchain-ollama) with token streaming.
"""
import json
from typing import AsyncGenerator

import httpx
from langchain_ollama import OllamaLLM

from backend.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from backend.rag.prompt import build_prompt
from backend.rag.retriever import retrieve
from backend.utils.logging import get_logger

log = get_logger(__name__)


def check_ollama() -> bool:
    """
    Verify that the Ollama server is reachable and the configured model exists.

    Returns:
        True if Ollama is running and the model is available.

    Raises:
        RuntimeError: If Ollama is unreachable or the model is not pulled.
    """
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(
            f"Ollama is not running at {OLLAMA_BASE_URL}. "
            f"Start it with: ollama serve\nError: {exc}"
        ) from exc

    tags = resp.json()
    model_names = [m["name"] for m in tags.get("models", [])]
    # Check both "model:tag" and short "model" matches
    model_base = OLLAMA_MODEL.split(":")[0]
    found = any(
        m == OLLAMA_MODEL or m.startswith(model_base) for m in model_names
    )
    if not found:
        raise RuntimeError(
            f"Model '{OLLAMA_MODEL}' is not available in Ollama. "
            f"Pull it with: ollama pull {OLLAMA_MODEL}\n"
            f"Available models: {model_names}"
        )
    log.info("Ollama OK — model '%s' is available.", OLLAMA_MODEL)
    return True


async def stream_answer(question: str) -> AsyncGenerator[str, None]:
    """
    Retrieve relevant context and stream an LLM-generated answer token by token.

    The function:
      1. Retrieves top-k chunks from ChromaDB.
      2. Builds a grounded RAG prompt.
      3. Streams tokens from Ollama, yielding each as a JSON-lines string.

    Each yielded item is a JSON line:
      {"token": "..."}   — intermediate token
      {"done": true, "sources": [...]}  — final message with source citations

    Args:
        question: User question string.

    Yields:
        JSON-lines strings suitable for a FastAPI StreamingResponse.
    """
    # Retrieve context
    chunks = retrieve(question)

    # Emit sources immediately so the client can render citations
    sources = [
        {"source": c["source"], "page": c["page"], "distance": c["distance"]}
        for c in chunks
    ]

    # Build prompt
    prompt = build_prompt(question, chunks)
    log.info("Generating answer for: %r  (%d context chunks)", question[:60], len(chunks))

    # Stream from Ollama
    llm = OllamaLLM(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        streaming=True,
    )

    try:
        async for token in llm.astream(prompt):
            yield json.dumps({"token": token}) + "\n"
    except Exception as exc:
        log.error("LLM generation error: %s", exc)
        yield json.dumps({"error": str(exc)}) + "\n"
        return

# Final message with source citations
    yield json.dumps({"done": True, "sources": sources}) + "\n"


async def federated_stream_answer(
    question: str,
    federated_retriever,  # FederatedRetriever | None
) -> AsyncGenerator[str, None]:
    """
    Federated version of stream_answer.

    If a FederatedRetriever is provided and peers are connected, broadcasts the
    query and fuses results before generating. Falls back to local-only if no
    retriever is available.

    Each yielded item is a JSON line:
      {"token": "..."}     — LLM token
      {"federation": {...}} — federation metadata (peer count, query_id, etc.)
      {"done": true, "sources": [...]}  — final with citations

    Args:
        question: User question string.
        federated_retriever: FederatedRetriever instance or None.

    Yields:
        JSON-lines strings.
    """
    if federated_retriever is not None:
        # Federated path
        result = await federated_retriever.query(question)
        chunks = result.chunks

        # Emit federation metadata first
        yield json.dumps({
            "federation": {
                "query_id": result.query_id,
                "local_chunks": result.local_count,
                "peer_chunks": result.peer_count,
                "peers_responded": result.peers_responded,
                "duration_ms": result.duration_ms,
            }
        }) + "\n"
    else:
        # Local-only fallback
        from backend.rag.retriever import retrieve
        chunks = retrieve(question)

    sources = [
        {
            "source": c.get("source", "unknown"),
            "page": c.get("page", 0),
            "node_id": c.get("node_id", "local"),
            "rrf_score": c.get("rrf_score"),
            "cid": c.get("cid", "")[:12] if c.get("cid") else None,
        }
        for c in chunks
    ]

    prompt = build_prompt(question, chunks)
    log.info(
        "Generating federated answer: %r (%d chunks, %d peers)",
        question[:60],
        len(chunks),
        len(getattr(getattr(federated_retriever, '_adapter', None), 'get_peers', lambda: [])()) if federated_retriever else 0,
    )

    llm = OllamaLLM(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        streaming=True,
    )

    try:
        async for token in llm.astream(prompt):
            yield json.dumps({"token": token}) + "\n"
    except Exception as exc:
        log.error("LLM generation error: %s", exc)
        yield json.dumps({"error": str(exc)}) + "\n"
        return

    yield json.dumps({"done": True, "sources": sources}) + "\n"

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

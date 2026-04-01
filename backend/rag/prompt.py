"""
Prompt templates for the AURA RAG pipeline.
Keeps the LLM grounded exclusively on retrieved context.
"""

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are AURA, a secure, local-first knowledge assistant.
Your answers must be grounded EXCLUSIVELY in the provided context excerpts.
Rules:
- If the answer cannot be found in the context, reply: "I don't have enough information in the ingested documents to answer that."
- Do NOT use any general knowledge that is not present in the context.
- Cite the source document and page number for every factual claim you make.
- Be concise and precise. Avoid filler phrases.
"""

# ── RAG prompt template ───────────────────────────────────────────────────────
RAG_TEMPLATE = """\
{system}

=== CONTEXT EXCERPTS ===
{context}
========================

USER QUESTION: {question}

ANSWER (cite sources):"""


def build_prompt(question: str, context_chunks: list[dict]) -> str:
    """
    Construct the full RAG prompt from retrieved context chunks.

    Args:
        question: The user's question string.
        context_chunks: List of dicts with keys 'text', 'source', 'page'.

    Returns:
        Formatted prompt string ready to send to the LLM.
    """
    if not context_chunks:
        context_text = "(No relevant documents found in the knowledge base.)"
    else:
        parts = []
        for i, chunk in enumerate(context_chunks, 1):
            source = chunk.get("source", "unknown")
            page = chunk.get("page", "?")
            text = chunk.get("text", "")
            parts.append(f"[{i}] Source: {source}, Page {page}\n{text}")
        context_text = "\n\n".join(parts)

    return RAG_TEMPLATE.format(
        system=SYSTEM_PROMPT,
        context=context_text,
        question=question,
    )

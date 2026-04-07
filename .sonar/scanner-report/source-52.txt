"""
Unit tests for backend.rag.prompt.
Tests prompt template construction and formatting.
"""

import pytest

from backend.rag.prompt import (
    SYSTEM_PROMPT,
    RAG_TEMPLATE,
    build_prompt,
)


class TestPromptTemplates:
    """Tests for prompt template constants."""

    def test_system_prompt_exists(self):
        """SYSTEM_PROMPT should be a non-empty string."""
        assert SYSTEM_PROMPT
        assert len(SYSTEM_PROMPT) > 10

    def test_rag_template_has_placeholders(self):
        """RAG_TEMPLATE should contain format placeholders."""
        assert "{system}" in RAG_TEMPLATE
        assert "{context}" in RAG_TEMPLATE
        assert "{question}" in RAG_TEMPLATE

    def test_system_prompt_contains_rules(self):
        """System prompt should contain grounding rules."""
        assert "grounded" in SYSTEM_PROMPT.lower() or "context" in SYSTEM_PROMPT.lower()


class TestBuildPrompt:
    """Tests for build_prompt()."""

    def test_empty_context_message(self):
        """Empty context should produce 'no relevant documents' message."""
        prompt = build_prompt("What is AURA?", [])
        assert (
            "no relevant documents" in prompt.lower() or "not found" in prompt.lower()
        )

    def test_single_chunk_formatting(self):
        """Single chunk should be formatted with source and page."""
        chunks = [
            {"text": "AURA is a sovereign node.", "source": "readme.md", "page": 1}
        ]
        prompt = build_prompt("What is AURA?", chunks)
        assert "AURA is a sovereign node" in prompt
        assert "readme.md" in prompt

    def test_multiple_chunks_indexed(self):
        """Multiple chunks should be indexed with [1], [2], etc."""
        chunks = [
            {"text": "First fact.", "source": "doc1.txt", "page": 1},
            {"text": "Second fact.", "source": "doc2.txt", "page": 42},
        ]
        prompt = build_prompt("Test question?", chunks)
        assert "[1]" in prompt
        assert "[2]" in prompt
        assert "First fact" in prompt
        assert "Second fact" in prompt

    def test_question_included(self):
        """Question should appear in the output."""
        question = "What year was AURA created?"
        chunks = [{"text": "Created in 2025.", "source": "src.txt", "page": 1}]
        prompt = build_prompt(question, chunks)
        assert question in prompt

    def test_system_prompt_included(self):
        """System prompt should be in the output."""
        chunks = [{"text": "Content.", "source": "f.txt", "page": 1}]
        prompt = build_prompt("Q?", chunks)
        assert SYSTEM_PROMPT in prompt

    def test_missing_source_defaults_to_unknown(self):
        """Chunk without source should use 'unknown'."""
        chunks = [{"text": "Some text.", "page": 1}]
        prompt = build_prompt("Q?", chunks)
        assert "unknown" in prompt.lower()

    def test_missing_page_defaults_to_question_mark(self):
        """Chunk without page should use '?'."""
        chunks = [{"text": "Some text.", "source": "f.txt"}]
        prompt = build_prompt("Q?", chunks)
        assert "Page ?" in prompt or "page ?" in prompt.lower()

    def test_missing_text_treated_as_empty(self):
        """Chunk without text should not crash."""
        chunks = [{"source": "f.txt", "page": 1}]
        prompt = build_prompt("Q?", chunks)
        assert prompt  # Should not raise

    def test_large_context_truncation(self):
        """Many chunks should all be included (no artificial limit)."""
        chunks = [
            {"text": f"Chunk {i}.", "source": f"doc{i}.txt", "page": i}
            for i in range(20)
        ]
        prompt = build_prompt("Q?", chunks)
        assert "Chunk 0" in prompt
        assert "Chunk 19" in prompt

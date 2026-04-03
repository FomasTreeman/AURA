"""
Unit tests for backend.ingestion.parser.
Tests PDF parsing logic.
"""

import pytest


class TestPageContent:
    """Tests for PageContent dataclass."""

    def test_page_content_creation(self):
        """PageContent should store page_num and text."""
        from backend.ingestion.parser import PageContent

        page = PageContent(page_num=1, text="Hello world")
        assert page.page_num == 1
        assert page.text == "Hello world"

    def test_page_content_with_empty_text(self):
        """PageContent should accept empty text."""
        from backend.ingestion.parser import PageContent

        page = PageContent(page_num=5, text="")
        assert page.page_num == 5
        assert page.text == ""


class TestParserConstants:
    """Tests for parser module constants."""

    def test_batch_size_defined(self):
        """BATCH_SIZE should be a positive integer."""
        from backend.ingestion.parser import BATCH_SIZE

        assert BATCH_SIZE > 0
        assert isinstance(BATCH_SIZE, int)

    def test_batch_size_reasonable(self):
        """BATCH_SIZE should be reasonable for memory management."""
        from backend.ingestion.parser import BATCH_SIZE

        assert BATCH_SIZE >= 10
        assert BATCH_SIZE <= 100

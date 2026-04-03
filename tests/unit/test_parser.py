"""
Unit tests for backend.ingestion.parser.
Tests PDF parsing logic with mocked PyMuPDF.
"""

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest


class TestPageContent:
    """Tests for PageContent dataclass."""

    def test_page_content_creation(self):
        """PageContent should store page_num and text."""
        from backend.ingestion.parser import PageContent

        page = PageContent(page_num=1, text="Hello world")
        assert page.page_num == 1
        assert page.text == "Hello world"


class TestParsePdf:
    """Tests for parse_pdf()."""

    def test_raises_on_missing_file(self):
        """parse_pdf() should raise FileNotFoundError for missing files."""
        from backend.ingestion.parser import parse_pdf

        with pytest.raises(FileNotFoundError):
            list(parse_pdf(Path("/nonexistent/file.pdf")))

    @patch("backend.ingestion.parser.fitz")
    def test_raises_on_invalid_pdf(self, mock_fitz):
        """parse_pdf() should raise ValueError for invalid PDF."""
        mock_fitz.open.side_effect = Exception("Invalid PDF")
        from backend.ingestion.parser import parse_pdf

        with pytest.raises(ValueError, match="Cannot open PDF"):
            list(parse_pdf(Path("test.pdf")))

    @patch("backend.ingestion.parser.fitz")
    def test_yields_batches_of_pages(self, mock_fitz):
        """parse_pdf() should yield pages in batches."""
        mock_page1 = MagicMock()
        mock_page1.get_text.return_value = "Page 1 content"
        mock_page2 = MagicMock()
        mock_page2.get_text.return_value = "Page 2 content"
        mock_page3 = MagicMock()
        mock_page3.get_text.return_value = "Page 3 content"

        mock_doc = MagicMock()
        mock_doc.page_count = 3
        mock_doc.__iter__ = lambda self: iter([mock_page1, mock_page2, mock_page3])
        mock_doc.close = MagicMock()
        mock_fitz.open.return_value = mock_doc

        from backend.ingestion.parser import parse_pdf, BATCH_SIZE

        batches = list(parse_pdf(Path("test.pdf")))

        assert len(batches) == 1  # All 3 pages fit in one batch (default BATCH_SIZE=20)
        assert len(batches[0]) == 3

    @patch("backend.ingestion.parser.fitz")
    def test_skips_empty_pages(self, mock_fitz):
        """parse_pdf() should skip pages with no extractable text."""
        mock_page_with_text = MagicMock()
        mock_page_with_text.get_text.return_value = "Has text"
        mock_page_empty = MagicMock()
        mock_page_empty.get_text.return_value = "   \n\t"

        mock_doc = MagicMock()
        mock_doc.page_count = 2
        mock_doc.__iter__ = lambda self: iter([mock_page_with_text, mock_page_empty])
        mock_doc.close = MagicMock()
        mock_fitz.open.return_value = mock_doc

        from backend.ingestion.parser import parse_pdf

        batches = list(parse_pdf(Path("test.pdf")))

        assert len(batches[0]) == 1  # Only one page with text

    @patch("backend.ingestion.parser.fitz")
    def test_page_numbers_are_one_indexed(self, mock_fitz):
        """Page numbers should be 1-based (first page = 1)."""
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Content"

        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_doc.__iter__ = lambda self: iter([mock_page])
        mock_doc.close = MagicMock()
        mock_fitz.open.return_value = mock_doc

        from backend.ingestion.parser import parse_pdf

        batches = list(parse_pdf(Path("test.pdf")))

        assert batches[0][0].page_num == 1

    @patch("backend.ingestion.parser.fitz")
    def test_closes_document(self, mock_fitz):
        """parse_pdf() should close the document after parsing."""
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Content"

        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_doc.__iter__ = lambda self: iter([mock_page])
        mock_doc.close = MagicMock()
        mock_fitz.open.return_value = mock_doc

        from backend.ingestion.parser import parse_pdf

        list(parse_pdf(Path("test.pdf")))

        mock_doc.close.assert_called_once()


class TestParsePdfFlat:
    """Tests for parse_pdf_flat()."""

    @patch("backend.ingestion.parser.fitz")
    def test_returns_flat_list(self, mock_fitz):
        """parse_pdf_flat() should return a flat list of all pages."""
        mock_page1 = MagicMock()
        mock_page1.get_text.return_value = "Page 1"
        mock_page2 = MagicMock()
        mock_page2.get_text.return_value = "Page 2"

        mock_doc = MagicMock()
        mock_doc.page_count = 2
        mock_doc.__iter__ = lambda self: iter([mock_page1, mock_page2])
        mock_doc.close = MagicMock()
        mock_fitz.open.return_value = mock_doc

        from backend.ingestion.parser import parse_pdf_flat

        pages = parse_pdf_flat(Path("test.pdf"))

        assert isinstance(pages, list)
        assert len(pages) == 2
        assert pages[0].text == "Page 1"
        assert pages[1].text == "Page 2"

    @patch("backend.ingestion.parser.fitz")
    def test_returns_empty_list_for_empty_pdf(self, mock_fitz):
        """parse_pdf_flat() should return empty list for PDF with no text."""
        mock_page = MagicMock()
        mock_page.get_text.return_value = "   "

        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_doc.__iter__ = lambda self: iter([mock_page])
        mock_doc.close = MagicMock()
        mock_fitz.open.return_value = mock_doc

        from backend.ingestion.parser import parse_pdf_flat

        pages = parse_pdf_flat(Path("test.pdf"))

        assert pages == []

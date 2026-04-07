"""
PDF parser for AURA ingestion pipeline.
Uses PyMuPDF (fitz) for fast, reliable text extraction.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

import fitz  # PyMuPDF

from backend.utils.logging import get_logger

log = get_logger(__name__)

BATCH_SIZE = 20  # pages to yield per batch to limit memory usage


@dataclass
class PageContent:
    """Represents the extracted text content of a single PDF page."""

    page_num: int   # 1-based page number
    text: str       # raw extracted text


def parse_pdf(path: Path) -> Generator[list[PageContent], None, None]:
    """
    Parse a PDF file and yield batches of PageContent objects.

    Yields pages in batches of BATCH_SIZE to avoid loading an entire
    500-page document into memory at once.

    Args:
        path: Path to the PDF file.

    Yields:
        List[PageContent] batches of at most BATCH_SIZE pages.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not a valid PDF or has no extractable text.
    """
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise ValueError(f"Cannot open PDF '{path}': {exc}") from exc

    total = doc.page_count
    log.info("Parsing '%s' (%d pages)", path.name, total)

    batch: list[PageContent] = []
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        if text:
            batch.append(PageContent(page_num=i + 1, text=text))
        if len(batch) >= BATCH_SIZE:
            yield batch
            batch = []

    if batch:
        yield batch

    doc.close()
    log.info("Parsed '%s' — %d pages extracted", path.name, total)


def parse_pdf_flat(path: Path) -> list[PageContent]:
    """
    Parse a PDF file and return all pages as a flat list.

    Convenience wrapper around parse_pdf for small documents.

    Args:
        path: Path to the PDF file.

    Returns:
        List of PageContent objects, one per non-empty page.
    """
    pages: list[PageContent] = []
    for batch in parse_pdf(path):
        pages.extend(batch)
    return pages

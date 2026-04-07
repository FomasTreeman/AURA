"""
Root conftest.py – shared pytest fixtures for the AURA test suite.
"""
import io
import os
import tempfile
from pathlib import Path

import pytest

# ── Ensure project root is in sys.path for absolute imports ──────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent))


# ── Environment overrides for testing ────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_env(tmp_path, monkeypatch):
    """
    Redirect ChromaDB and ingest directories to a fresh temp directory
    for each test, so tests never touch production data.
    """
    chroma_dir = tmp_path / "chroma_test"
    ingest_dir = tmp_path / "docs_test"
    chroma_dir.mkdir()
    ingest_dir.mkdir()
    monkeypatch.setenv("CHROMA_PATH", str(chroma_dir))
    monkeypatch.setenv("INGEST_DIR", str(ingest_dir))
    # Force config module to re-resolve paths with new env vars
    import backend.config as cfg
    cfg.CHROMA_PATH = chroma_dir
    cfg.INGEST_DIR = ingest_dir
    # Reset the ChromaDB singleton so each test gets a fresh client
    import backend.database.chroma as chroma_mod
    chroma_mod._client = None
    yield
    # Tear down: reset singleton again
    chroma_mod._client = None


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """
    Create a minimal real PDF file using fitz (PyMuPDF) for ingestion tests.
    Contains two pages with known text, including PII.
    """
    import fitz

    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()

    # Page 1 – general content
    page1 = doc.new_page()
    page1.insert_text(
        (72, 72),
        "Q3 Revenue Report\n\nOur total revenue for Q3 was $4.2 million.\n"
        "The primary driver was the new enterprise product line.",
    )

    # Page 2 – PII-heavy content
    page2 = doc.new_page()
    page2.insert_text(
        (72, 72),
        "Employee Record\n\nName: John Smith\n"
        "Email: john.smith@example.com\n"
        "SSN: 523-78-2345\n"
        "Phone: 555-867-5309\n"
        "This record is confidential.",
    )

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def large_pdf(tmp_path) -> Path:
    """Create a 25-page PDF to test batched processing."""
    import fitz

    pdf_path = tmp_path / "large.pdf"
    doc = fitz.open()
    for i in range(25):
        page = doc.new_page()
        page.insert_text(
            (72, 72),
            f"Page {i + 1} of the large document.\n"
            f"This page discusses topic {i + 1} in detail.\n"
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        )
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def corrupted_pdf(tmp_path) -> Path:
    """Create a file named .pdf that contains garbage bytes."""
    bad = tmp_path / "corrupted.pdf"
    bad.write_bytes(b"NOT A PDF FILE - random garbage \x00\x01\x02\x03")
    return bad

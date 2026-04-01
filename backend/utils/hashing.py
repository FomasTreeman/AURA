"""
Hashing utilities for AURA backend.
Provides deterministic SHA-256 document content IDs (CIDs).
"""
import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    """
    Compute the SHA-256 hash of a file's raw bytes.

    Args:
        path: Path to the file.

    Returns:
        Hex-encoded SHA-256 digest string (64 characters).

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """
    Compute the SHA-256 hash of raw bytes.

    Args:
        data: Byte string to hash.

    Returns:
        Hex-encoded SHA-256 digest string (64 characters).
    """
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str, encoding: str = "utf-8") -> str:
    """
    Compute the SHA-256 hash of a text string.

    Args:
        text: String to hash.
        encoding: Text encoding (default utf-8).

    Returns:
        Hex-encoded SHA-256 digest string (64 characters).
    """
    return sha256_bytes(text.encode(encoding))

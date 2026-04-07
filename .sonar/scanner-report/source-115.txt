"""
IPFS content addressing for AURA document integrity.

Computes IPFS CIDv1 identifiers purely in Python (no daemon required).
Optionally validates against a running IPFS HTTP API.

CIDv1 format (raw codec, sha2-256):
  bytes = version_varint(1) + codec_varint(0x55) + multihash
  multihash = hash_fn_varint(0x12) + digest_len_varint(0x20) + sha256(content)
  encoded = 'b' + base32_lower(bytes)   # multibase prefix 'b' = base32 lowercase

This matches `ipfs add --cid-version=1 --raw-leaves -Q <file>`.

IPFS daemon HTTP API (optional):
  Base URL: http://localhost:5001/api/v0
  Add file: POST /add?cid-version=1&raw-leaves=true
  Get CID:  parse response JSON for "Hash" field
"""
import base64
import hashlib
import struct
from pathlib import Path
from typing import Optional

import httpx

from backend.utils.logging import get_logger

log = get_logger(__name__)

_IPFS_API_BASE = "http://localhost:5001/api/v0"
_MULTICODEC_RAW = 0x55        # raw binary codec
_MULTIHASH_SHA256 = 0x12      # sha2-256 function code
_SHA256_DIGEST_LEN = 0x20     # 32 bytes
_MULTIBASE_BASE32_PREFIX = "b"


def _encode_varint(n: int) -> bytes:
    """Encode an unsigned integer as an unsigned LEB128 varint."""
    buf = []
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            buf.append(byte | 0x80)
        else:
            buf.append(byte)
            break
    return bytes(buf)


def _base32_encode(data: bytes) -> str:
    """Encode bytes to lowercase base32 without padding."""
    return base64.b32encode(data).decode().rstrip("=").lower()


def compute_cid_v1(data: bytes) -> str:
    """
    Compute the CIDv1 of raw bytes (raw codec, sha2-256 multihash).

    This is equivalent to:
        echo -n <data> | ipfs add --cid-version=1 --raw-leaves -Q

    Args:
        data: Raw bytes to hash.

    Returns:
        CIDv1 string starting with 'b' (base32 multibase prefix).
    """
    digest = hashlib.sha256(data).digest()  # 32 bytes

    # Build multihash: function_code + digest_length + digest
    multihash = (
        _encode_varint(_MULTIHASH_SHA256)
        + _encode_varint(_SHA256_DIGEST_LEN)
        + digest
    )

    # Build CIDv1: version(1) + codec(raw) + multihash
    cid_bytes = (
        _encode_varint(1)
        + _encode_varint(_MULTICODEC_RAW)
        + multihash
    )

    return _MULTIBASE_BASE32_PREFIX + _base32_encode(cid_bytes)


def compute_file_cid(path: Path) -> str:
    """
    Compute the CIDv1 of a file's raw content.

    Reads the file in 64 KB chunks to handle large files efficiently.

    Args:
        path: Path to the file.

    Returns:
        CIDv1 string.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    digest = h.digest()

    multihash = (
        _encode_varint(_MULTIHASH_SHA256)
        + _encode_varint(_SHA256_DIGEST_LEN)
        + digest
    )
    cid_bytes = (
        _encode_varint(1)
        + _encode_varint(_MULTICODEC_RAW)
        + multihash
    )
    return _MULTIBASE_BASE32_PREFIX + _base32_encode(cid_bytes)


def verify_cid(
    path: Path,
    expected_cid: str,
) -> bool:
    """
    Verify that a file's content matches an expected CIDv1.

    Args:
        path: Path to the file to verify.
        expected_cid: Expected CIDv1 string.

    Returns:
        True if the computed CID matches the expected CID.
    """
    try:
        actual = compute_file_cid(path)
        match = actual == expected_cid
        if not match:
            log.warning(
                "CID mismatch for '%s': expected=%s, actual=%s",
                path.name,
                expected_cid[:20],
                actual[:20],
            )
        return match
    except FileNotFoundError:
        log.error("CID verification failed: file not found: %s", path)
        return False


def verify_cid_bytes(data: bytes, expected_cid: str) -> bool:
    """
    Verify raw bytes against an expected CIDv1.

    Args:
        data: Raw bytes.
        expected_cid: Expected CIDv1 string.

    Returns:
        True if the computed CID matches.
    """
    actual = compute_cid_v1(data)
    return actual == expected_cid


async def add_file_to_ipfs_daemon(
    path: Path,
    api_base: str = _IPFS_API_BASE,
) -> str | None:
    """
    Add a file to the IPFS daemon and return its CIDv1.

    Falls back gracefully if the daemon is not running.

    Args:
        path: Path to the file to add.
        api_base: IPFS HTTP API base URL.

    Returns:
        CIDv1 string from the daemon, or None if daemon unavailable.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            with open(path, "rb") as fh:
                response = await client.post(
                    f"{api_base}/add",
                    params={"cid-version": "1", "raw-leaves": "true"},
                    files={"file": (path.name, fh, "application/octet-stream")},
                )
            response.raise_for_status()
            data = response.json()
            daemon_cid = data.get("Hash")
            log.info("IPFS daemon CID for '%s': %s", path.name, daemon_cid)
            return daemon_cid
    except Exception as exc:
        log.debug("IPFS daemon unavailable (falling back to local CID): %s", exc)
        return None


def is_valid_cid_v1(cid: str) -> bool:
    """
    Check if a string looks like a valid CIDv1 (base32, starts with 'b').

    Args:
        cid: CID string to validate.

    Returns:
        True if it passes basic structural validation.
    """
    if not cid or not cid.startswith(_MULTIBASE_BASE32_PREFIX):
        return False
    # base32 chars: a-z, 2-7
    valid_chars = set("abcdefghijklmnopqrstuvwxyz234567")
    return all(c in valid_chars for c in cid[1:])

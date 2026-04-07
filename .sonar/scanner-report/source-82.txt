"""
PII redaction module for AURA ingestion pipeline.
Uses regex patterns to scrub sensitive entities before chunking/embedding.
"""

import re
from functools import lru_cache

from backend.utils.logging import get_logger

log = get_logger(__name__)

_REDACT_PLACEHOLDER = "<REDACTED>"

# Regex patterns for PII entities
_PATTERNS = {
    "EMAIL_ADDRESS": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "PHONE_NUMBER": re.compile(
        r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b"
    ),
    "US_SSN": re.compile(r"\b[0-9]{3}[-\s]?[0-9]{2}[-\s]?[0-9]{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:[0-9]{4}[-\s]?){3}[0-9]{4}\b"),
    "IP_ADDRESS": re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
    "IBAN_CODE": re.compile(
        r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}(?:[A-Z0-9]?){0,16}\b"
    ),
    "DATE": re.compile(
        r"\b(?:[0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4}|[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2})\b"
    ),
}

# Patterns requiring context (more complex)
_EMAIL_PATTERN = _PATTERNS["EMAIL_ADDRESS"]
_PHONE_PATTERN = _PATTERNS["PHONE_NUMBER"]
_SSN_PATTERN = _PATTERNS["US_SSN"]
_CC_PATTERN = _PATTERNS["CREDIT_CARD"]
_IP_PATTERN = _PATTERNS["IP_ADDRESS"]
_IBAN_PATTERN = _PATTERNS["IBAN_CODE"]

# Names are hard to detect reliably without ML, so we focus on structural PII
# PERSON detection is intentionally excluded — too many false positives


@lru_cache(maxsize=1)
def _get_patterns() -> dict:
    """Return compiled regex patterns for PII detection."""
    return _PATTERNS


def redact(text: str, language: str = "en") -> str:
    """
    Detect and replace PII entities in text with '<REDACTED>'.

    Uses regex patterns for reliable structural PII detection:
    - Email addresses
    - Phone numbers
    - Social Security Numbers
    - Credit card numbers
    - IP addresses
    - IBAN codes

    Args:
        text: Raw text that may contain PII.
        language: Language code (currently unused, English only).

    Returns:
        Text with all detected PII replaced by '<REDACTED>'.
    """
    if not text or not text.strip():
        return text

    redacted = text

    # Redact email addresses
    redacted = _EMAIL_PATTERN.sub(_REDACT_PLACEHOLDER, redacted)

    # Redact phone numbers
    redacted = _PHONE_PATTERN.sub(_REDACT_PLACEHOLDER, redacted)

    # Redact SSN (only if it looks like one)
    redacted = _SSN_PATTERN.sub(
        lambda m: _REDACT_PLACEHOLDER if _looks_like_ssn(m.group()) else m.group(),
        redacted,
    )

    # Redact credit cards (only if valid length)
    redacted = _CC_PATTERN.sub(
        lambda m: _REDACT_PLACEHOLDER
        if _looks_like_credit_card(m.group())
        else m.group(),
        redacted,
    )

    # Redact IP addresses
    redacted = _IP_PATTERN.sub(
        lambda m: _REDACT_PLACEHOLDER if _looks_like_ip(m.group()) else m.group(),
        redacted,
    )

    # Redact IBAN codes
    redacted = _IBAN_PATTERN.sub(_REDACT_PLACEHOLDER, redacted)

    return redacted


def _looks_like_ssn(text: str) -> bool:
    """Check if a number string looks like a SSN."""
    digits = re.sub(r"\D", "", text)
    if len(digits) != 9:
        return False
    # SSN cannot start with 000, 666, or 900-999
    first_three = int(digits[:3])
    if first_three == 0 or first_three == 666 or first_three >= 900:
        return False
    return True


def _looks_like_credit_card(text: str) -> bool:
    """Check if a number string looks like a credit card (passes Luhn)."""
    digits = re.sub(r"\D", "", text)
    if len(digits) < 13 or len(digits) > 19:
        return False
    # Simple Luhn check
    total = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _looks_like_ip(text: str) -> bool:
    """Check if a string looks like a valid IP address."""
    parts = text.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        try:
            n = int(part)
            if n < 0 or n > 255:
                return False
        except ValueError:
            return False
    return True


def redact_batch(texts: list[str], language: str = "en") -> list[str]:
    """
    Redact PII from a batch of text strings.

    Args:
        texts: List of raw text strings.
        language: Language code (default 'en').

    Returns:
        List of redacted strings, same length and order as input.
    """
    return [redact(t, language=language) for t in texts]

"""
PII redaction module for AURA ingestion pipeline.
Wraps Microsoft Presidio to scrub sensitive entities before chunking/embedding.
"""
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from backend.utils.logging import get_logger

log = get_logger(__name__)

# PII entity types to detect and redact.
# DATE_TIME and NRP are intentionally excluded — they produce too many false
# positives (e.g. "quarterly", "year") on typical enterprise document text.
_ENTITIES = [
    "PERSON",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "US_SSN",
    "CREDIT_CARD",
    "LOCATION",
    "IBAN_CODE",
    "IP_ADDRESS",
]

_REDACT_PLACEHOLDER = "<REDACTED>"


@lru_cache(maxsize=1)
def _get_engines() -> tuple[AnalyzerEngine, AnonymizerEngine]:
    """
    Lazily initialise and cache the Presidio Analyzer and Anonymizer engines.

    Returns:
        Tuple of (AnalyzerEngine, AnonymizerEngine).
    """
    log.info("Loading Presidio engines (first call – may take a moment)…")
    analyzer = AnalyzerEngine()
    anonymizer = AnonymizerEngine()
    log.info("Presidio engines ready.")
    return analyzer, anonymizer


def redact(text: str, language: str = "en") -> str:
    """
    Detect and replace PII entities in text with '<REDACTED>'.

    Presidio is run with a conservative default threshold so that
    common entities are reliably caught. The function is deterministic
    for the same input.

    Args:
        text: Raw text that may contain PII.
        language: Language code for the NLP model (default 'en').

    Returns:
        Text with all detected PII replaced by '<REDACTED>'.
    """
    if not text or not text.strip():
        return text

    analyzer, anonymizer = _get_engines()

    results = analyzer.analyze(
        text=text,
        entities=_ENTITIES,
        language=language,
    )

    if not results:
        return text

    operators = {
        entity: OperatorConfig("replace", {"new_value": _REDACT_PLACEHOLDER})
        for entity in _ENTITIES
    }

    anonymized = anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators=operators,
    )
    return anonymized.text


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

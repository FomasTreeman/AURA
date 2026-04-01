"""
Unit tests for backend.ingestion.redactor.
Verifies that Presidio correctly detects and replaces PII entities.
"""
import pytest

from backend.ingestion.redactor import redact, redact_batch


REDACTED = "<REDACTED>"


class TestRedactBasic:
    """Basic redaction correctness tests."""

    def test_email_is_redacted(self):
        """Email addresses must be redacted."""
        text = "Contact us at john.smith@example.com for support."
        result = redact(text)
        assert "john.smith@example.com" not in result
        assert REDACTED in result

    def test_credit_card_is_redacted(self):
        """Credit card numbers must be redacted."""
        # Luhn-valid test card number (Visa test card)
        text = "Payment card on file: 4111111111111111."
        result = redact(text)
        assert "4111111111111111" not in result

    def test_ssn_is_redacted(self):
        """US Social Security Numbers must be redacted."""
        # 523-78-2345: area=523 (valid), group=78 (valid), serial=2345 (valid)
        text = "Employee SSN: 523-78-2345."
        result = redact(text)
        assert "523-78-2345" not in result
        assert REDACTED in result

    def test_person_name_is_redacted(self):
        """Named persons must be detected and redacted."""
        text = "The report was signed by John Smith on Monday."
        result = redact(text)
        assert "John Smith" not in result

    def test_no_pii_text_unchanged(self):
        """Text with no PII entities must be returned unchanged."""
        text = "The quarterly revenue grew by 12 percent year over year."
        result = redact(text)
        assert result == text

    def test_empty_string(self):
        """Empty input must return empty string without error."""
        assert redact("") == ""

    def test_whitespace_only(self):
        """Whitespace-only input is returned as-is."""
        result = redact("   ")
        assert result.strip() == ""


class TestRedactMultiplePII:
    """Test that multiple PII types in one string are all redacted."""

    def test_multiple_entities_all_redacted(self):
        """All PII in a multi-entity string should be removed."""
        # Use a detectable SSN: area=523 (valid), group=78 (valid), serial=2345
        text = (
            "Name: Alice Johnson. "
            "Email: alice@corp.com. "
            "SSN: 523-78-2345."
        )
        result = redact(text)
        assert "Alice Johnson" not in result
        assert "alice@corp.com" not in result
        assert "523-78-2345" not in result

    def test_non_pii_content_preserved(self):
        """Non-PII content must survive redaction."""
        text = "Revenue was $4.2 million. Contact: ceo@company.com"
        result = redact(text)
        assert "Revenue was" in result
        assert "$4.2 million" in result
        assert "ceo@company.com" not in result


class TestRedactBatch:
    """Tests for redact_batch()."""

    def test_batch_same_length(self):
        """Output list must have the same length as input list."""
        texts = [
            "Card: 4111111111111111",
            "No PII here",
            "Email: test@test.com",
        ]
        results = redact_batch(texts)
        assert len(results) == len(texts)

    def test_batch_order_preserved(self):
        """Non-PII items must pass through in original order."""
        texts = ["alpha", "beta", "gamma"]
        results = redact_batch(texts)
        assert results == texts

    def test_batch_each_item_redacted(self):
        """Each item in the batch is independently redacted."""
        # Use confirmed-detectable SSN formats
        texts = ["SSN: 523-78-2345", "Email: test@company.com"]
        results = redact_batch(texts)
        assert "523-78-2345" not in results[0]
        assert "test@company.com" not in results[1]

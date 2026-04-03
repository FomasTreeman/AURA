"""
Unit tests for backend.ingestion.redactor.
Verifies that regex-based PII detection correctly identifies and replaces entities.
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

    def test_phone_number_is_redacted(self):
        """Phone numbers must be redacted."""
        text = "Call us at 555-123-4567 for support."
        result = redact(text)
        assert "555-123-4567" not in result
        assert REDACTED in result

    def test_ip_address_is_redacted(self):
        """IP addresses must be redacted."""
        text = "Server IP: 192.168.1.100"
        result = redact(text)
        assert "192.168.1.100" not in result
        assert REDACTED in result

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
        text = "Contact: alice@corp.com. Phone: 555-123-4567. SSN: 523-78-2345."
        result = redact(text)
        assert "alice@corp.com" not in result
        assert "555-123-4567" not in result
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
        texts = ["SSN: 523-78-2345", "Email: test@company.com"]
        results = redact_batch(texts)
        assert "523-78-2345" not in results[0]
        assert "test@company.com" not in results[1]


class TestRedactEdgeCases:
    """Edge case tests for redaction."""

    def test_invalid_ssn_not_redacted(self):
        """Invalid SSN patterns should not be redacted."""
        # SSN starting with 000 is invalid
        text = "Number: 000-12-3456"
        result = redact(text)
        assert "000-12-3456" in result  # Should not be redacted

    def test_invalid_cc_not_redacted(self):
        """Invalid credit card numbers should not be redacted."""
        # Number that fails Luhn check
        text = "Card: 1234567890123456"
        result = redact(text)
        assert "1234567890123456" in result  # Should not be redacted

    def test_iban_detected(self):
        """IBAN codes should be redacted."""
        text = "Account: DE89370400440532013000"
        result = redact(text)
        assert "DE89370400440532013000" not in result
        assert REDACTED in result

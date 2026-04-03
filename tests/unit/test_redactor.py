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


class TestRedactPhoneFormats:
    """Tests for various phone number formats."""

    def test_phone_dashed(self):
        """Dashed phone format should be redacted."""
        text = "Call 555-123-4567"
        result = redact(text)
        assert "555-123-4567" not in result
        assert REDACTED in result

    def test_phone_parentheses(self):
        """Phone with area code in parentheses should be redacted."""
        text = "Call (555) 123-4567"
        result = redact(text)
        assert "(555) 123-4567" not in result
        assert REDACTED in result

    def test_phone_with_country_code(self):
        """International phone with country code should be redacted."""
        text = "Call +1-555-123-4567"
        result = redact(text)
        assert "+1-555-123-4567" not in result
        assert REDACTED in result

    def test_phone_dot_separated(self):
        """Dot-separated phone format should be redacted."""
        text = "Call 555.123.4567"
        result = redact(text)
        assert "555.123.4567" not in result
        assert REDACTED in result

    def test_phone_no_format(self):
        """Plain 10-digit phone should be redacted."""
        text = "Call 5551234567"
        result = redact(text)
        assert "5551234567" not in result
        assert REDACTED in result


class TestRedactEmailFormats:
    """Tests for various email formats."""

    def test_email_standard(self):
        """Standard email should be redacted."""
        text = "Contact user@domain.com"
        result = redact(text)
        assert "user@domain.com" not in result
        assert REDACTED in result

    def test_email_subdomain(self):
        """Email with subdomain should be redacted."""
        text = "Email: john.doe@mail.company.org"
        result = redact(text)
        assert "john.doe@mail.company.org" not in result
        assert REDACTED in result

    def test_email_plus_addressing(self):
        """Email with plus addressing should be redacted."""
        text = "Send to alice+test@gmail.com"
        result = redact(text)
        assert "alice+test@gmail.com" not in result
        assert REDACTED in result


class TestRedactIPAddresses:
    """Tests for IP address detection."""

    def test_ipv4_standard(self):
        """Standard IPv4 should be redacted."""
        text = "Server: 10.0.0.1"
        result = redact(text)
        assert "10.0.0.1" not in result
        assert REDACTED in result

    def test_ipv4_loopback(self):
        """Loopback address should be redacted."""
        text = "Localhost: 127.0.0.1"
        result = redact(text)
        assert "127.0.0.1" not in result
        assert REDACTED in result

    def test_ipv4_invalid_out_of_range(self):
        """Invalid IP with out-of-range octets should not be redacted."""
        text = "Number: 256.0.0.1"
        result = redact(text)
        assert "256.0.0.1" in result

    def test_ipv4_private_range(self):
        """Private IP range should be redacted."""
        text = "NAT: 192.168.1.100"
        result = redact(text)
        assert "192.168.1.100" not in result
        assert REDACTED in result


class TestRedactIBAN:
    """Tests for IBAN detection."""

    def test_iban_german(self):
        """German IBAN should be redacted."""
        text = "Account: DE89370400440532013000"
        result = redact(text)
        assert "DE89370400440532013000" not in result

    def test_iban_uk(self):
        """UK IBAN should be redacted."""
        text = "GB82WEST12345698765432"
        result = redact(text)
        assert "GB82WEST12345698765432" not in result

    def test_iban_french(self):
        """French IBAN should be redacted."""
        text = "FR1420041010050500013M02606"
        result = redact(text)
        assert "FR1420041010050500013M02606" not in result


class TestGetPatterns:
    """Tests for _get_patterns function."""

    def test_get_patterns_returns_dict(self):
        """_get_patterns should return a dict."""
        from backend.ingestion.redactor import _get_patterns

        patterns = _get_patterns()
        assert isinstance(patterns, dict)

    def test_get_patterns_contains_expected_keys(self):
        """_get_patterns should contain expected entity types."""
        from backend.ingestion.redactor import _get_patterns

        patterns = _get_patterns()
        expected = [
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "US_SSN",
            "CREDIT_CARD",
            "IP_ADDRESS",
            "IBAN_CODE",
        ]
        for key in expected:
            assert key in patterns

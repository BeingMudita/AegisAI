"""Tests for data-loss prevention redaction."""

from app.firewall.dlp import redact


def test_secrets_always_redacted() -> None:
    text = "key sk-abcdefghijklmnopqrstuvwxyz123 and password: hunter2"
    result = redact(text, pii=False)
    assert "sk-abc" not in result.text
    assert "hunter2" not in result.text
    assert result.redactions == {"API_KEY": 1, "CREDENTIAL": 1}


def test_pii_redacted_only_when_requested() -> None:
    text = "Contact ana@northwind.example or +44 20-7946-0958"
    assert redact(text, pii=False).text == text
    out = redact(text, pii=True).text
    assert "northwind" not in out
    assert "7946" not in out


def test_card_numbers_need_valid_luhn() -> None:
    out = redact("4111 1111 1111 1111 vs 1234 5678 9012 3456").text
    assert out == "[CARD REDACTED] vs 1234 5678 9012 3456"


def test_business_figures_untouched() -> None:
    text = "INV-2041 for 12500.0 is due 2026-09-01; revenue $4.2M up 12%."
    result = redact(text)
    assert result.text == text
    assert not result.redacted

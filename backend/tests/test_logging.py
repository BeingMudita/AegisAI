"""Logging must never fail a request because of console encoding."""

import io

from app.telemetry.logging import _SafeStream


def test_unencodable_text_is_degraded_not_raised() -> None:
    raw = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    stream = _SafeStream(raw)
    stream.write("trust fell LOW → UNTRUSTED\n")
    stream.flush()
    raw.seek(0)
    assert raw.read() == "trust fell LOW \\u2192 UNTRUSTED\n"

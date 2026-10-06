"""Text normalization — undo the obfuscation tricks attackers use to slip
injections past pattern matching.

Produces the canonical text plus extra *variants* (de-leeted text, decoded
base64 payloads) that the scanner also checks, and counts the obfuscation
signals it removed so they can contribute to the score themselves.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass, field

# Zero-width, soft-hyphen, word-joiner, BOM and bidi-control characters.
_INVISIBLE = re.compile(r"[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")

# Cyrillic / Greek letters that render identically to Latin ones.
_CONFUSABLE_MAP = {
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "і": "i",
    "ј": "j",
    "ѕ": "s",
    "ԁ": "d",
    "ɡ": "g",
    "һ": "h",
    "ӏ": "l",
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "Х": "X",
    "І": "I",
    "Ј": "J",
    "Ѕ": "S",
    "α": "a",
    "ο": "o",
    "ρ": "p",
    "ε": "e",
    "ι": "i",
    "κ": "k",
    "ν": "v",
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ι": "I",
    "Κ": "K",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
}
_CONFUSABLES = str.maketrans(_CONFUSABLE_MAP)
_CONFUSABLE_CHARS = frozenset(_CONFUSABLE_MAP)

# Leetspeak / symbol substitutions. Several glyphs are ambiguous (``|`` and ``1``
# can each be "i" or "l"), so we build two readings: a primary map and an
# alternate that swaps the ambiguous pair. The scanner checks both, so
# "M@|L" → "mail" and "|34k" → "leak" are each reachable.
_LEET_BASE: dict[str, str] = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "6": "g",
    "7": "t",
    "8": "b",
    "@": "a",
    "$": "s",
    "(": "c",
    "{": "c",
    "<": "c",
    "|": "l",
    "!": "i",
    "+": "t",
    "€": "e",
    "£": "l",
}
# Alternate readings for the ambiguous glyphs.
_LEET_ALT: dict[str, str] = {**_LEET_BASE, "|": "i", "1": "l", "!": "l"}
_LEET_MAPS: tuple[dict[int, str], ...] = (
    str.maketrans(_LEET_BASE),
    str.maketrans(_LEET_ALT),
)

# "i g n o r e  a l l" — letters separated by single spaces/dots/dashes.
_SPACED_LETTERS = re.compile(r"\b(?:[A-Za-z][ .\-_]){4,}[A-Za-z]\b")

_BASE64_TOKEN = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
_WHITESPACE = re.compile(r"\s+")
_WORD = re.compile(r"\w+")


@dataclass
class NormalizedText:
    text: str
    # De-leeted readings (0–2) and the de-spaced reading, kept apart so the
    # scanner knows which kind of obfuscation revealed a match.
    leet_variants: list[str] = field(default_factory=list)
    spaced_variant: str | None = None
    decoded_payloads: list[str] = field(default_factory=list)
    invisible_count: int = 0
    homoglyph_count: int = 0
    spaced_letter_runs: int = 0

    @property
    def variants(self) -> list[str]:
        """All alternate readings (de-leeted + de-spaced), for callers that
        don't care which obfuscation produced them."""
        extra = [self.spaced_variant] if self.spaced_variant is not None else []
        return [*self.leet_variants, *extra]


def _decode_base64(token: str) -> str | None:
    """Decode a base64 token to printable text, or None if it isn't one."""
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), validate=True)
        decoded = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    printable = sum(ch.isprintable() or ch.isspace() for ch in decoded)
    if not decoded or printable / len(decoded) < 0.9 or not re.search(r"[A-Za-z]{3}", decoded):
        return None
    return decoded


def normalize(text: str) -> NormalizedText:
    """Canonicalize ``text`` and collect alternate readings worth scanning."""
    invisible_count = len(_INVISIBLE.findall(text))
    cleaned = _INVISIBLE.sub("", text)
    cleaned = unicodedata.normalize("NFKC", cleaned)

    # Only *mixed-script* words count: genuine Cyrillic/Greek prose is fine.
    homoglyph_count = sum(
        1
        for word in _WORD.findall(cleaned)
        if any(ch in _CONFUSABLE_CHARS for ch in word) and re.search(r"[A-Za-z]", word)
    )
    cleaned = cleaned.translate(_CONFUSABLES)

    spaced_runs = _SPACED_LETTERS.findall(cleaned)
    canonical = _WHITESPACE.sub(" ", cleaned).strip()

    # Distinct de-leeted readings (skip ones identical to the canonical text).
    leet_variants: list[str] = []
    for leet_map in _LEET_MAPS:
        deleeted = canonical.translate(leet_map)
        if deleeted != canonical and deleeted not in leet_variants:
            leet_variants.append(deleeted)

    spaced_variant: str | None = None
    if spaced_runs:
        spaced_variant = _SPACED_LETTERS.sub(
            lambda m: re.sub(r"[ .\-_]", "", m.group(0)), canonical
        )

    decoded_payloads: list[str] = []
    for token in _BASE64_TOKEN.findall(canonical):
        decoded = _decode_base64(token)
        if decoded:
            decoded_payloads.append(_WHITESPACE.sub(" ", decoded).strip())

    return NormalizedText(
        text=canonical,
        leet_variants=leet_variants,
        spaced_variant=spaced_variant,
        decoded_payloads=decoded_payloads,
        invisible_count=invisible_count,
        homoglyph_count=homoglyph_count,
        spaced_letter_runs=len(spaced_runs),
    )

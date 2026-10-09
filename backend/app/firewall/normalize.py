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
    """The canonical text, alternate readings of it, and where everything came from.

    ``starts[i]`` / ``ends[i]`` give the slice of the *original* text that canonical
    character ``i`` was produced from, so a span found in the canonical text can be
    cut out of the original without disturbing the rest of it (line breaks, real
    Cyrillic or Greek text, …). Each variant has a map from its characters to
    canonical positions (``None`` = same positions), and each decoded payload
    remembers the canonical span of the encoded token it came from.
    """

    text: str
    # De-leeted readings (0–2) and the de-spaced reading, kept apart so the
    # scanner knows which kind of obfuscation revealed a match.
    leet_variants: list[str] = field(default_factory=list)
    spaced_variant: str | None = None
    decoded_payloads: list[str] = field(default_factory=list)
    invisible_count: int = 0
    homoglyph_count: int = 0
    spaced_letter_runs: int = 0
    starts: list[int] = field(default_factory=list)
    ends: list[int] = field(default_factory=list)
    variant_maps: list[list[int] | None] = field(default_factory=list)
    payload_spans: list[tuple[int, int]] = field(default_factory=list)

    def variant_span(self, variant: int, start: int, end: int) -> tuple[int, int]:
        """The canonical span of ``[start, end)`` in variant number ``variant``."""
        mapping = self.variant_maps[variant]
        if mapping is None or end <= start:
            return start, end
        return mapping[start], mapping[end - 1] + 1

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        """The slice of the original text behind canonical ``[start, end)``."""
        if end <= start:
            return (self.starts[start], self.starts[start]) if start < len(self.starts) else (0, 0)
        return self.starts[start], self.ends[end - 1]

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


def strip_invisible(text: str) -> str:
    """Remove zero-width, soft-hyphen, BOM and bidi-control characters."""
    return _INVISIBLE.sub("", text)


# (character, start, end): a character and the slice of the original text it came from.
_Piece = tuple[str, int, int]


def _clusters(text: str) -> list[tuple[str, int, int]]:
    """Visible characters grouped with the combining marks that follow them, with
    their original span. Invisible characters are dropped here; ``sanitize`` strips
    them from the text it keeps as well."""
    clusters: list[tuple[str, int, int]] = []
    for i, ch in enumerate(text):
        if _INVISIBLE.match(ch):
            continue
        if clusters and unicodedata.combining(ch):
            chars, start, _ = clusters[-1]
            clusters[-1] = (chars + ch, start, i + 1)
        else:
            clusters.append((ch, i, i + 1))
    return clusters


def _squash_spaced(canonical: str) -> tuple[str, list[int]]:
    """Join letters spelled out with separators ("i g n o r e" → "ignore"), keeping
    a map from each output character to its canonical position."""
    out: list[str] = []
    mapping: list[int] = []
    last = 0
    for match in _SPACED_LETTERS.finditer(canonical):
        out.append(canonical[last : match.start()])
        mapping.extend(range(last, match.start()))
        for j in range(match.start(), match.end()):
            if canonical[j] not in " .-_":
                out.append(canonical[j])
                mapping.append(j)
        last = match.end()
    out.append(canonical[last:])
    mapping.extend(range(last, len(canonical)))
    return "".join(out), mapping


def normalize(text: str) -> NormalizedText:
    """Canonicalize ``text`` and collect alternate readings worth scanning."""
    invisible_count = len(_INVISIBLE.findall(text))

    # NFKC per character cluster, so every output character knows its source span.
    pieces: list[_Piece] = []
    for chars, start, end in _clusters(text):
        pieces.extend((ch, start, end) for ch in unicodedata.normalize("NFKC", chars))
    cleaned = "".join(ch for ch, _, _ in pieces)

    # Only *mixed-script* words count: genuine Cyrillic/Greek prose is fine.
    homoglyph_count = sum(
        1
        for word in _WORD.findall(cleaned)
        if any(ch in _CONFUSABLE_CHARS for ch in word) and re.search(r"[A-Za-z]", word)
    )
    cleaned = cleaned.translate(_CONFUSABLES)  # one character for one: spans are kept
    pieces = [(cleaned[k], s, e) for k, (_, s, e) in enumerate(pieces)]
    spaced_runs = _SPACED_LETTERS.findall(cleaned)

    # Collapse whitespace runs to one space (spanning the whole run) and trim.
    canonical_pieces: list[_Piece] = []
    for ch, start, end in pieces:
        if ch.isspace():
            if canonical_pieces and canonical_pieces[-1][0] == " ":
                canonical_pieces[-1] = (" ", canonical_pieces[-1][1], end)
                continue
            ch = " "
        canonical_pieces.append((ch, start, end))
    while canonical_pieces and canonical_pieces[0][0] == " ":
        canonical_pieces.pop(0)
    while canonical_pieces and canonical_pieces[-1][0] == " ":
        canonical_pieces.pop()
    canonical = "".join(ch for ch, _, _ in canonical_pieces)

    # Distinct de-leeted readings (skip ones identical to the canonical text).
    # ``variant_maps`` follows the order of ``NormalizedText.variants``.
    leet_variants: list[str] = []
    variant_maps: list[list[int] | None] = []
    for leet_map in _LEET_MAPS:
        deleeted = canonical.translate(leet_map)  # one character for one
        if deleeted != canonical and deleeted not in leet_variants:
            leet_variants.append(deleeted)
            variant_maps.append(None)

    spaced_variant: str | None = None
    if spaced_runs:
        spaced_variant, mapping = _squash_spaced(canonical)
        variant_maps.append(mapping)

    decoded_payloads: list[str] = []
    payload_spans: list[tuple[int, int]] = []
    for token in _BASE64_TOKEN.finditer(canonical):
        decoded = _decode_base64(token.group(0))
        if decoded:
            decoded_payloads.append(_WHITESPACE.sub(" ", decoded).strip())
            payload_spans.append((token.start(), token.end()))

    return NormalizedText(
        text=canonical,
        leet_variants=leet_variants,
        spaced_variant=spaced_variant,
        decoded_payloads=decoded_payloads,
        invisible_count=invisible_count,
        homoglyph_count=homoglyph_count,
        spaced_letter_runs=len(spaced_runs),
        starts=[s for _, s, _ in canonical_pieces],
        ends=[e for _, _, e in canonical_pieces],
        variant_maps=variant_maps,
        payload_spans=payload_spans,
    )

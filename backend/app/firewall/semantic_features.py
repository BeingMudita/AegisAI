"""Low-level feature primitives for the semantic layer.

Kept separate from ``semantic.py`` so ``lexicon.py`` can share the stemmer
without a circular import: this module depends on nothing else in the firewall.
"""

from __future__ import annotations

import math
import re
import zlib

#: Bumped whenever the feature space changes, so a model trained on the old
#: space is refused at load time instead of scoring against mismatched hashes.
FEATURE_VERSION = 2
HASH_BITS = 18
_MASK = (1 << HASH_BITS) - 1
_WORD = re.compile(r"[a-z0-9]+")
_SUFFIXES = ("ing", "ied", "ies", "ed", "es", "ly", "s")
MAX_CHARS = 8000  # longer text is scored on its first 8,000 characters


def stem(word: str) -> str:
    """A crude, dependency-free stemmer — strips one common suffix."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def hash_feature(feature: str) -> int:
    return zlib.crc32(feature.encode("utf-8")) & _MASK


def tokenize(text_lower: str) -> list[str]:
    """Stemmed word tokens of already-lowercased text."""
    return [stem(w) for w in _WORD.findall(text_lower)]


def l2_normalize(indices: set[int]) -> dict[int, float]:
    """Binary features, L2-normalised to unit length."""
    value = 1.0 / math.sqrt(len(indices)) if indices else 0.0
    return dict.fromkeys(indices, value)

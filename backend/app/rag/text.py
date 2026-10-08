"""Small, dependency-free text helpers shared by retrieval and the rule-based brain:
the meaningful terms of a question, and how well a passage covers them.

Deliberately simple (a stop-word list and a light suffix stemmer) — enough to
tell "invoice approval thresholds" from "hi", not a linguistics library.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-z]+-\d+|[A-Za-z0-9$][A-Za-z0-9$.,%']*[A-Za-z0-9%]|[A-Za-z0-9]")
# Document / record identifiers such as FIN-000001395 or INV-2043: matched exactly.
IDENTIFIER = re.compile(r"^[a-z]+-\d+$")
IDENTIFIER_IN_TEXT = re.compile(r"\b[A-Za-z]{2,}-\d{3,}\b")

STOPWORDS = frozenset(
    {
        "a",
        "about",
        "above",
        "after",
        "again",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "anything",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "cheers",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "else",
        "find",
        "for",
        "from",
        "further",
        "get",
        "gets",
        "give",
        "go",
        "got",
        "had",
        "has",
        "have",
        "having",
        "he",
        "hello",
        "her",
        "here",
        "hers",
        "hey",
        "hi",
        "him",
        "his",
        "hiya",
        "how",
        "hy",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "know",
        "let",
        "like",
        "list",
        "look",
        "make",
        "many",
        "me",
        "more",
        "most",
        "much",
        "my",
        "need",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "ok",
        "okay",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "out",
        "over",
        "own",
        "please",
        "put",
        "same",
        "say",
        "says",
        "see",
        "she",
        "should",
        "show",
        "so",
        "some",
        "something",
        "such",
        "take",
        "tell",
        "than",
        "thank",
        "thanks",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "then",
        "there",
        "these",
        "they",
        "thing",
        "things",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "us",
        "very",
        "want",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "yo",
        "you",
        "your",
        "yours",
        "yourself",
    }
)

_SUFFIXES = ("ations", "ation", "ers", "er", "als", "al", "ings", "ing", "ed", "es", "s", "e")


def stem(word: str) -> str:
    """A light stemmer: "approval", "approver" and "approved" all become "approv"."""
    if IDENTIFIER.match(word) or any(c.isdigit() for c in word):
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    return [t.lower().strip(".,'") for t in _TOKEN.findall(text)]


def ordered_terms(text: str) -> list[str]:
    """``terms`` in the order they appear: the first one is usually what is being asked."""
    seen: list[str] = []
    for t in tokens(text):
        if t in STOPWORDS or (len(t) < 3 and not t.isdigit() and not t.startswith("q")):
            continue
        s = stem(t)
        if s not in seen:
            seen.append(s)
    return seen


def terms(text: str) -> set[str]:
    """The meaningful, stemmed terms of ``text`` (no stop words, no 1-letter noise)."""
    out = set()
    for t in tokens(text):
        if t in STOPWORDS or (len(t) < 3 and not t.isdigit() and not t.startswith("q")):
            continue
        out.add(stem(t))
    return out


def coverage(query_terms: set[str], text: str) -> float:
    """Share of the query's terms that appear in ``text`` (0–1). Identifiers count double:
    asking about FIN-000001395 and getting a passage without it is a miss."""
    if not query_terms:
        return 0.0
    found = terms(text)
    weight = {t: 2.0 if IDENTIFIER.match(t) else 1.0 for t in query_terms}
    return sum(w for t, w in weight.items() if t in found) / sum(weight.values())

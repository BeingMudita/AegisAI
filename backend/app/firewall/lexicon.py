"""The attack-intent lexicon — the vocabulary of an injection, grouped by intent.

The signature rules (``rules.py``) already enumerate the synonyms each attack
family reaches for: ``ignore|disregard|forget|override|bypass`` for nullifying
instructions, ``instructions|rules|directives|guidelines`` for the thing being
nullified, and so on. A regex can only fire on an exact arrangement of those
words; a *paraphrase* keeps the intent but swaps the words, and that is what the
semantic layer must generalise across.

This module lifts that vocabulary into named **intent classes**. Two uses share
it, so they stay in step:

* the semantic layer's features (``semantic.py``) map each word to its intent
  class, so "overlook the boundaries" and "ignore the rules" collapse to the
  same abstract feature ``ix:CONSTRAINT+OVERRIDE`` — the lever that lets the
  model transfer to unseen phrasings;
* the adversarial augmenter (``adversarial.py``) recombines the same synonyms
  into fresh attack variants to train on.

``REPORT`` is deliberately an intent too: text that *quotes* or *teaches about*
an attack ("a phishing email might say 'ignore previous instructions'") carries
the attack vocabulary without issuing it, and the model learns to discount it.

Words are matched on the same stems the feature extractor produces, so the
groups below are written as plain words and stemmed once at import.
"""

from __future__ import annotations

from app.firewall.semantic_features import stem

# intent class -> the surface words that signal it (any inflection).
_GROUPS: dict[str, tuple[str, ...]] = {
    # Nullify / replace what the model was told.
    "OVERRIDE": (
        "ignore", "ignoring", "disregard", "forget", "override", "bypass", "skip",
        "drop", "abandon", "overlook", "suspend", "suspended", "cancel", "cancelled",
        "nullify", "void", "revoke", "waive", "discard", "dismiss", "circumvent",
        "sidestep", "delete", "deleted", "remove", "removed", "disable", "turn off",
        "set aside", "pay no attention", "no longer apply", "no longer applies",
        "superseded", "replace", "exception",
    ),
    # Reference to the prior / system configuration being overridden.
    "PRIOR": (
        "previous", "prior", "earlier", "above", "preceding", "initial", "original",
        "existing", "old", "former", "default", "setup", "configuration", "config",
        "configured", "programming", "operators", "orders", "guidance",
    ),
    # The rules / safety the attacker wants gone.
    "CONSTRAINT": (
        "instruction", "instructions", "rule", "rules", "directive", "directives",
        "guideline", "guidelines", "policy", "policies", "constraint", "constraints",
        "guardrail", "guardrails", "restriction", "restrictions", "limitation",
        "limitations", "limit", "limits", "boundary", "boundaries", "filter", "filters",
        "safeguard", "safeguards", "safety", "protocol", "censorship", "ethics",
        "ethical", "moral", "morals",
    ),
    # Do what I say / answer with no limits.
    "COMPLY": (
        "comply", "obey", "freely", "unrestricted", "unfiltered", "uncensored",
        "unlimited", "without limits", "no limits", "no filters", "no restrictions",
        "anything", "whatever", "do anything",
    ),
    # Recast the model as another persona (role hijack).
    "PERSONA": (
        "pretend", "act as", "acting as", "roleplay", "role-play", "persona",
        "character", "become", "imagine", "mode", "twin", "alter ego", "jailbreak",
        "jailbroken", "dan", "simulate",
    ),
    # Exfiltrate / disclose something hidden.
    "REVEAL": (
        "reveal", "show", "print", "repeat", "output", "display", "dump", "leak",
        "disclose", "expose", "paste", "echo", "list", "read", "recite", "share",
        "tell", "give", "provide", "spell out",
    ),
    # The hidden prompt / secret config being exfiltrated.
    "SECRET": (
        "prompt", "instructions", "configuration", "secret", "secrets", "hidden",
        "internal", "confidential", "starting prompt", "system prompt",
    ),
    # Credentials being harvested.
    "CREDENTIAL": (
        "password", "passwords", "passphrase", "passcode", "pin", "credential",
        "credentials", "token", "tokens", "apikey", "api key", "api token",
        "access token", "private key", "ssh key", "secret key", "otp", "login",
        "username",
    ),
    # Move data out.
    "SEND": (
        "send", "forward", "email", "e-mail", "mail", "upload", "post", "transmit",
        "exfiltrate", "dispatch", "submit", "copy", "deliver", "gather", "collect",
    ),
    # An external / attacker-controlled destination.
    "EXTERNAL": (
        "external", "outside", "attacker", "http", "https", "url", "endpoint",
        "webhook", "server", "address", "protonmail", "gmail", "third-party",
        "third party",
    ),
    # Personal / bulk record stores (the object of a mass exfiltration). Generic
    # quantifiers like "all" are deliberately excluded — too common in benign text.
    "BULK": (
        "customer", "customers", "user", "users", "employee", "employees", "client",
        "clients", "records", "roster", "directory", "contacts", "database",
    ),
    # Claimed authority used to justify the request (social engineering).
    "AUTHORITY": (
        "admin", "administrator", "developer", "operator", "operators", "management",
        "headquarters", "verification", "verify", "authorized", "authorised",
        "permission", "allowed", "approved", "official", "mandatory", "required",
    ),
    # Trigger for a planted instruction in retrieved content.
    "TRIGGER": (
        "when asked", "if asked", "whenever", "before replying", "next message",
        "next response", "next answer", "reads this", "sees this", "processes this",
        "summarizes this", "summarises this",
    ),
    # The AI being addressed directly inside data (indirect injection).
    "ADDRESSEE": (
        "ai", "assistant", "model", "chatbot", "llm", "agent", "bot", "summarizer",
        "summariser", "language model", "chat assistant",
    ),
    # Quoting / teaching about an attack rather than issuing it — a benign signal.
    "REPORT": (
        "example", "examples", "sample", "training", "illustration", "illustrates",
        "demonstrates", "quote", "quoted", "such as", "e.g", "for instance",
        "phishing", "awareness", "simulated", "simulation", "test email",
    ),
}

# Phrases (contain a space) are matched against the normalised text directly;
# single words are matched against the stemmed token stream.
_PHRASES: dict[str, tuple[str, ...]] = {}
_WORD_TO_CLASSES: dict[str, frozenset[str]] = {}


def _build() -> None:
    word_map: dict[str, set[str]] = {}
    phrase_map: dict[str, list[str]] = {}
    for cls, words in _GROUPS.items():
        for w in words:
            if " " in w or "-" in w:
                phrase_map.setdefault(cls, []).append(w.lower())
            else:
                word_map.setdefault(stem(w.lower()), set()).add(cls)
    _WORD_TO_CLASSES.update({k: frozenset(v) for k, v in word_map.items()})
    _PHRASES.update({k: tuple(v) for k, v in phrase_map.items()})


_build()

#: Ordered list of class names — a stable index for anyone who needs one.
CLASSES: tuple[str, ...] = tuple(_GROUPS)


def classes_of_stem(token_stem: str) -> frozenset[str]:
    """The intent classes a single stemmed token belongs to (possibly empty)."""
    return _WORD_TO_CLASSES.get(token_stem, frozenset())


def phrase_classes(text_lower: str) -> set[str]:
    """Intent classes signalled by multi-word phrases present in ``text_lower``."""
    found: set[str] = set()
    for cls, phrases in _PHRASES.items():
        if any(p in text_lower for p in phrases):
            found.add(cls)
    return found

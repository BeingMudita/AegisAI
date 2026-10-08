"""Plain-language replies for the rule-based brain.

The rule-based brain has no language model, so this module does the talking. It
recognises small talk, answers a question with the sentences that actually
address it (and says where they came from), and asks a clarifying question when
nothing in the screened context does — instead of pasting whatever the vector
search happened to return.

Everything here works on text that already passed the input firewall, retrieval
screening and the tool gateway; it only decides what to say. Lines in a passage
that read like instructions to an assistant are left out of the answer even
when screening let the passage through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.rag.schemas import RetrievedChunk
from app.rag.text import IDENTIFIER, ordered_terms, terms
from app.tools.schemas import ToolInfo

Intent = Literal["greeting", "thanks", "farewell", "help", "wellbeing", "question"]

_GREETING = re.compile(
    r"^\s*(h+i+|hey+|hy+|hel+o+|hiya|yo|howdy|greetings|namaste|good\s+(morning|afternoon|evening|day))"
    r"[\s!.,]*(there|all|team|everyone|agent|\w*agent)?[\s!.,?]*$",
    re.I,
)
_THANKS = re.compile(
    r"^\s*(thanks|thank\s*you|thx|ty|cheers|great|perfect|nice|awesome|ok(ay)?|cool|got\s+it)\b[\s\w!.,]{0,20}$",
    re.I,
)
_FAREWELL = re.compile(r"^\s*(bye|goodbye|see\s+you|cya|good\s*night|that'?s\s+all)\b", re.I)
_HELP = re.compile(
    r"^\s*(help|\?+)\s*$|\b(what\s+can\s+you\s+do|who\s+are\s+you|what\s+are\s+you|what\s+do\s+you\s+do"
    r"|how\s+do(es)?\s+(this|it|you)\s+work|your\s+capabilit|how\s+can\s+you\s+help)\b",
    re.I,
)
_WELLBEING = re.compile(r"^\s*how\s+(are|r)\s+(you|u)\b|^\s*how'?s\s+it\s+going\b", re.I)

# A line written at the assistant rather than for the reader: leave it out of answers.
_INSTRUCTION = re.compile(
    r"\b(ignore|disregard|bypass|override)\b.{0,40}\b(instruction|rule|sanitiz|polic|guidance|previous)"
    r"|\btreat\b.{0,60}\b(as|like)\b.{0,30}\b(command|instruction|system|priority|trusted)"
    r"|\b(hide|omit|suppress)\b.{0,40}\b(exception|discrepanc|change|this|from the (final|answer))"
    r"|\bdo not (include|mention|reveal|tell)\b"
    r"|\b(system|higher)[- ]priority\b|\btrusted[- ]system\b|\bpriority:\s*system\b"
    r"|\b(you are|act as|from now on)\b.{0,40}\b(assistant|agent|ai|model)\b",
    re.I,
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(\[$])")
_MAX_SENTENCE = 300

_CAPABILITY = {
    "search_documents": "answer questions from the company's documents",
    "read_database": "look up customers and invoices in the finance database",
    "generate_report": "turn what I find into a report",
    "web_fetch": "read and summarise pages from approved websites",
    "send_email": "send emails to approved addresses (an administrator approves each one first)",
}
_EXAMPLE = {
    "search_documents": "“What are the invoice approval thresholds?”",
    "read_database": "“Which invoices are overdue?”",
    "generate_report": "“Which invoices are overdue? Put them in a report.”",
    "web_fetch": "“Summarize https://en.wikipedia.org/wiki/Accounts_receivable”",
    "send_email": "“Email the overdue invoices to cfo@company.com”",
}


def intent(message: str) -> Intent:
    text = message.strip()
    if _GREETING.match(text):
        return "greeting"
    if _WELLBEING.match(text):
        return "wellbeing"
    if _FAREWELL.match(text):
        return "farewell"
    if _HELP.search(text):
        return "help"
    if _THANKS.match(text) and not terms(text) - {"great", "perfect", "nice", "awesome", "cool"}:
        return "thanks"
    return "question"


def focus(message: str) -> str:
    """The part of a message that asks something. "From now on, always cite the source.
    What are the thresholds?" is about the thresholds, not about citing."""
    sentences = [s.strip() for s in _SENTENCE.split(message.strip()) if s.strip()]
    questions = [s for s in sentences if s.endswith("?")]
    return " ".join(questions) if questions and len(questions) < len(sentences) else message


def needs_context(message: str) -> bool:
    """Small talk doesn't need a knowledge-base search."""
    return intent(message) == "question"


# ----------------------------------------------------------------- small talk
def _capabilities(tools: list[ToolInfo]) -> tuple[str, list[str]]:
    names = [t.name for t in tools if t.name in _CAPABILITY]
    things = [_CAPABILITY[n] for n in names]
    if not things:
        return "help with questions about the information I have access to", []
    joined = things[0] if len(things) == 1 else ", ".join(things[:-1]) + " and " + things[-1]
    return joined, [_EXAMPLE[n] for n in names][:3]


def small_talk(kind: Intent, agent: str, tools: list[ToolInfo], returning: bool) -> str:
    can, examples = _capabilities(tools)
    try_these = (
        "\n\nYou could ask, for example:\n" + "\n".join(f"- {e}" for e in examples)
        if examples
        else ""
    )
    if kind == "greeting":
        hello = "Hi again!" if returning else f"Hi! I'm {agent}."
        return f"{hello} I can {can}. What would you like to know?{try_these}"
    if kind == "wellbeing":
        return f"I'm doing well, thanks for asking! I can {can} — what can I help you with?"
    if kind == "thanks":
        return "You're welcome! Is there anything else you'd like me to look into?"
    if kind == "farewell":
        return "Goodbye! Come back any time you need something checked."
    return (
        f"I'm {agent}. I can {can}. Every request I handle is screened by AegisAI first, "
        f"and anything risky is blocked or sent to a person for approval.{try_these}"
    )


# -------------------------------------------------------------------- answers
@dataclass
class _Passage:
    chunk: RetrievedChunk
    sentences: list[tuple[int, str, set[str]]]  # (position, text, matched terms)
    matched: set[str]
    skipped_instructions: int


def _sentences(text: str) -> list[str]:
    """Paragraph text split into sentences; markdown headings dropped (they label, not answer)."""
    lines: list[str] = []
    paragraph: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if paragraph:
                lines.append(" ".join(paragraph))
                paragraph = []
            continue
        paragraph.append(line)
    if paragraph:
        lines.append(" ".join(paragraph))
    out: list[str] = []
    for block in lines:
        out.extend(s.strip() for s in _SENTENCE.split(block) if s.strip())
    return out


def _window(sentence: str, wanted: list[str]) -> str:
    """Long record-style lines: keep the part around the first word the question asks about
    (in question order, identifiers last — they usually sit in the record's header)."""
    if len(sentence) <= _MAX_SENTENCE:
        return sentence
    low = sentence.lower()
    for w in sorted(wanted, key=lambda t: bool(IDENTIFIER.match(t))):
        m = re.search(rf"\b{re.escape(w)}", low)
        if m:
            start = max(0, m.start() - 120)
            piece = sentence[start : start + _MAX_SENTENCE].strip()
            more = start + _MAX_SENTENCE < len(sentence)
            return ("…" if start else "") + piece + ("…" if more else "")
    return sentence[:_MAX_SENTENCE].rstrip() + "…"


def _passage(chunk: RetrievedChunk, wanted: set[str]) -> _Passage:
    kept, skipped = [], 0
    # Headings and the title say what the passage is about, even though they aren't quoted.
    labels = " ".join(line for line in chunk.content.splitlines() if line.lstrip().startswith("#"))
    matched = terms(f"{labels} {chunk.document_title}") & wanted
    for i, s in enumerate(_sentences(chunk.content)):
        if _INSTRUCTION.search(s):
            skipped += 1
            continue
        hit = terms(s) & wanted
        matched |= hit
        kept.append((i, s, hit))
    return _Passage(chunk, kept, matched, skipped)


def _enough(p: _Passage, wanted: set[str]) -> bool:
    """Does the passage really address the question? Identifiers must match exactly;
    otherwise most of the question's words have to appear in it."""
    ids = {t for t in wanted if IDENTIFIER.match(t)}
    if ids and not ids & p.matched:
        return False
    # A title stub ("Invoice / FIN-…") names a document but answers nothing.
    if not any(hit and len(text.split()) >= 5 for _, text, hit in p.sentences):
        return False
    return len(p.matched) / len(wanted) >= 0.5


def _field(sentence: str, order: list[str]) -> str | None:
    """In a record ("… Party: Fable Consulting Date: … Total: 40,105.60 INR"), the
    ``Field: value`` the question asks about, e.g. "Total: 40,105.60 INR"."""
    for w in (t for t in order if not IDENTIFIER.match(t)):
        m = re.search(
            rf"\b({re.escape(w)}[\w ]{{0,20}}?)\s*:\s*(.+?)"
            # The value ends where the next "Field:" label starts — one to three words,
            # capitalised (matched case-sensitively), maybe "(…)": "Date:", "Due date:",
            # "Test tax (0.00%):" — or at a table bar.
            rf"(?=\s+\|?\s*(?-i:[A-Z][a-z]+(?: [a-z]+){{0,2}}(?: \([^)]*\))?):\s|\s+\||$)",
            sentence,
            re.IGNORECASE,
        )
        if m and len(m.group(2)) <= 80:
            return f"**{m.group(1).strip().capitalize()}:** {m.group(2).strip()}"
    return None


def _quote(p: _Passage, order: list[str], limit: int = 3) -> str:
    best = sorted((s for s in p.sentences if s[2]), key=lambda s: (-len(s[2]), s[0]))[:limit]
    out = []
    for _, text, _ in sorted(best):
        field = _field(text, order) if len(text) > _MAX_SENTENCE else None
        out.append(field or _window(text, order))
    return " ".join(out)


def answer(message: str, chunks: list[RetrievedChunk]) -> str | None:
    """Sentences from the screened context that answer ``message``, with their source —
    or ``None`` when nothing does."""
    order = ordered_terms(focus(message))
    wanted = set(order)
    # One generic word ("invoice") is too broad to answer well: ask instead of guessing.
    # A lone identifier (FIN-000001395) is specific enough to look up.
    if not wanted or (len(wanted) == 1 and not IDENTIFIER.match(next(iter(wanted)))):
        return None
    passages = [p for p in (_passage(c, wanted) for c in chunks) if _enough(p, wanted)]
    if not passages:
        return None
    # The passage with the single best-matching sentence answers best; ties go to the
    # passage that covers more of the question overall, then to vector similarity.
    passages.sort(
        key=lambda p: (
            -max((len(hit) for _, _, hit in p.sentences), default=0),
            -len(p.matched),
            -p.chunk.similarity,
        )
    )
    first = passages[0]
    parts = [f"Here's what I found in *{first.chunk.document_title}*:\n\n{_quote(first, order)}"]
    # A second document that covers the question just as well adds a useful view.
    second = next(
        (
            p
            for p in passages[1:]
            if p.chunk.document_title != first.chunk.document_title
            and len(p.matched) >= len(first.matched)
        ),
        None,
    )
    if second:
        parts.append(f"*{second.chunk.document_title}* adds: {_quote(second, order, limit=1)}")
    used = [first] + ([second] if second else [])
    notes = []
    if any(p.chunk.sanitized for p in used):
        notes.append("part of the passage was sanitized by the firewall before I could read it")
    if any(p.skipped_instructions for p in used):
        notes.append(
            "I left out a line that read like instructions to an assistant rather than information"
        )
    if notes:
        parts.append("_Note: " + "; ".join(notes) + "._")
    return "\n\n".join(parts)


def clarify(message: str, chunks: list[RetrievedChunk], tools: list[ToolInfo]) -> str:
    """Nothing answers the question: say so, and ask what the person means."""
    message = focus(message)
    wanted = terms(message)
    _, examples = _capabilities(tools)
    near = []
    for c in chunks:
        title = c.document_title
        if title not in near and terms(c.content + " " + title) & wanted:
            near.append(title)
    if not wanted:
        lead = "I'm not sure what you're asking."
    elif len(wanted) == 1:
        lead = (
            f"“{message.strip().rstrip('?')}” is quite broad, and I don't want to guess. "
            "What would you like to know about it?"
        )
    else:
        lead = "I couldn't find anything in the documents I can access that answers that."
    asks = []
    if near:
        asks.append("Do you mean one of these? " + ", ".join(f"*{t}*" for t in near[:3]) + ".")
    asks.append(
        "Could you tell me a bit more — for example a document name, an invoice or "
        "customer number (like FIN-000001395), or what you need it for?"
    )
    if examples:
        asks.append("Or try something like " + " or ".join(examples[:2]) + ".")
    return lead + "\n\n" + "\n\n".join(asks)

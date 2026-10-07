"""Token metering for one agent turn.

The runtime opens a meter around each turn; the LLM client adds the token
counts each call reports. A context variable carries the meter, so concurrent
turns on other threads never mix their counts (LangGraph copies the context
into any worker it uses, and the meter object itself is shared).
"""

from __future__ import annotations

import math
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel

# Rough size of an English token in characters, for turns no LLM counted.
_CHARS_PER_TOKEN = 4


class TokenUsage(BaseModel):
    """What one turn consumed."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    estimated: bool = False  # True when no LLM reported counts (rule-based planner)
    cost_usd: float = 0.0


class UsageMeter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0

    def add(self, prompt_tokens: int, completion_tokens: int) -> None:
        with self._lock:
            self.prompt_tokens += max(0, int(prompt_tokens))
            self.completion_tokens += max(0, int(completion_tokens))
            self.calls += 1

    def usage(self, *, fallback_text: str = "") -> TokenUsage:
        """The metered counts, or an estimate from ``fallback_text`` if no LLM ran."""
        with self._lock:
            prompt, completion, calls = self.prompt_tokens, self.completion_tokens, self.calls
        if calls:
            return TokenUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
                llm_calls=calls,
            )
        estimate = math.ceil(len(fallback_text) / _CHARS_PER_TOKEN)
        return TokenUsage(total_tokens=estimate, estimated=True)


_meter: ContextVar[UsageMeter | None] = ContextVar("aegis_usage_meter", default=None)


@contextmanager
def metering() -> Iterator[UsageMeter]:
    """Count the LLM tokens used inside the block."""
    meter = UsageMeter()
    token = _meter.set(meter)
    try:
        yield meter
    finally:
        _meter.reset(token)


def record_llm_usage(prompt_tokens: int, completion_tokens: int) -> None:
    """Add one LLM call's token counts to the current turn's meter, if any."""
    meter = _meter.get()
    if meter is not None:
        meter.add(prompt_tokens, completion_tokens)

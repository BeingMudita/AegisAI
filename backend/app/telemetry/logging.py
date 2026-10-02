"""Structured-logging setup.

Console output in development, JSON lines in production. Writes go through a
stream wrapper that degrades characters the console can't encode (e.g. "→"
on a cp1252 Windows console) instead of raising — a log line must never
fail the request that produced it.
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

import structlog


class _SafeStream:
    """Proxy for a text stream that never raises UnicodeEncodeError."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        try:
            return self._stream.write(text)
        except UnicodeEncodeError:
            encoding = getattr(self._stream, "encoding", None) or "ascii"
            safe = text.encode(encoding, errors="backslashreplace").decode(encoding)
            return self._stream.write(safe)

    def flush(self) -> None:
        self._stream.flush()


def configure_logging(level: str = "INFO", *, json_logs: bool = False) -> None:
    """Configure structlog for the process."""
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=_SafeStream(sys.stdout)),  # type: ignore[arg-type]
        cache_logger_on_first_use=True,
    )

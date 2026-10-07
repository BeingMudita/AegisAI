"""Keyset pagination for newest-first lists.

A page is the next ``limit`` items strictly older than the cursor, ordered by
``(created_at, id)`` descending. Unlike offsets, pages stay stable while new
items arrive at the head. The cursor is opaque to clients (base64 of the last
item's key); a malformed one is a 400, not a crash.
"""

from __future__ import annotations

import base64
from datetime import datetime

from fastapi import HTTPException, status

Key = tuple[datetime, str]


def encode_cursor(created_at: datetime, item_id: str) -> str:
    raw = f"{created_at.isoformat()}|{item_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> Key | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, item_id = raw.split("|", 1)
        created = datetime.fromisoformat(stamp)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor.") from exc
    if created.tzinfo is None or not item_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor.")
    return created, item_id


def older_than(key: Key, before: Key | None) -> bool:
    """True when ``key`` sorts after the cursor in newest-first order."""
    return before is None or key < before

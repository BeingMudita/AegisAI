"""In-memory user store (Phase 1 placeholder).

This will be replaced by a database-backed store in a later phase. It exists
so JWT login works end-to-end during backend foundation work. Seeded with one
account per role; default passwords are for local development only.
"""

from __future__ import annotations

from app.auth.roles import Role
from app.auth.schemas import UserInDB
from app.auth.security import hash_password

# Local-dev seed accounts — do NOT ship these to production.
_SEED = [
    ("admin", "admin123", Role.ADMIN),
    ("analyst", "analyst123", Role.SECURITY_ANALYST),
    ("agent", "agent123", Role.AGENT),
]

_USERS: dict[str, UserInDB] = {
    username: UserInDB(
        username=username,
        role=role,
        hashed_password=hash_password(password),
    )
    for username, password, role in _SEED
}


def get_user(username: str) -> UserInDB | None:
    """Look up a user by username."""
    return _USERS.get(username)

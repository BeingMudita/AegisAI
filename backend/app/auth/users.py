"""User store.

In memory mode: one seeded account per role. With ``STORAGE_BACKEND=postgres``
users are read from the ``users`` table (the same accounts are seeded there on
first start). Seed passwords come from SEED_*_PASSWORD; the defaults are for
local development only and production refuses to start with them.
"""

from __future__ import annotations

from app.auth.roles import Role
from app.auth.schemas import UserInDB
from app.auth.security import hash_password
from app.config import get_settings

# Seed accounts. Passwords come from SEED_*_PASSWORD; the defaults are for
# local development only and production refuses to start with them.
_settings = get_settings()
_SEED = [
    ("admin", _settings.seed_admin_password, Role.ADMIN),
    ("analyst", _settings.seed_analyst_password, Role.SECURITY_ANALYST),
    ("agent", _settings.seed_agent_password, Role.AGENT),
]

_USERS: dict[str, UserInDB] = (
    {}
    if _settings.use_postgres
    else {
        username: UserInDB(username=username, role=role, hashed_password=hash_password(password))
        for username, password, role in _SEED
    }
)


def get_user(username: str) -> UserInDB | None:
    """Look up a user by username."""
    if _settings.use_postgres:
        from app.persistence.identity import get_db_user

        return get_db_user(username)
    return _USERS.get(username)

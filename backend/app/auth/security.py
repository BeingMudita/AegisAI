"""Password hashing and JWT token creation/validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.auth.roles import Role
from app.auth.schemas import TokenData
from app.config import get_settings

settings = get_settings()

# bcrypt operates on at most 72 bytes; longer inputs are truncated to match.
_BCRYPT_MAX_BYTES = 72


def _prep(password: str) -> bytes:
    """Encode and clamp a password to bcrypt's 72-byte limit."""
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password``."""
    return bcrypt.hashpw(_prep(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Check ``plain`` against a stored bcrypt ``hashed`` value."""
    try:
        return bcrypt.checkpw(_prep(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_access_token(
    *,
    username: str,
    role: Role,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT carrying the subject and role claims."""
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": username,
        "role": role.value,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> TokenData | None:
    """Decode and validate a JWT, returning its claims or ``None`` if invalid."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None

    username = payload.get("sub")
    role_raw = payload.get("role")
    if username is None or role_raw is None:
        return None
    try:
        role = Role(role_raw)
    except ValueError:
        return None
    return TokenData(username=username, role=role)

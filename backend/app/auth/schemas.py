"""Pydantic schemas for authentication."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.auth.roles import Role


class Token(BaseModel):
    """OAuth2-style bearer token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds.")


class TokenData(BaseModel):
    """Decoded JWT claims we care about."""

    username: str
    role: Role


class User(BaseModel):
    """Public-facing user representation."""

    username: str
    role: Role
    disabled: bool = False
    # The tenant (organisation) this user belongs to; isolation is scoped to it.
    tenant: str = "default"


class UserInDB(User):
    """User as stored, including the password hash. Never serialized to clients."""

    hashed_password: str


class LoginRequest(BaseModel):
    """JSON login payload (alternative to the OAuth2 form)."""

    username: str
    password: str

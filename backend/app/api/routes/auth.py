"""Authentication routes — login and current-user info."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.auth.dependencies import get_current_user
from app.auth.limiter import account_limiter, login_limiter
from app.auth.schemas import Token, User
from app.auth.security import create_access_token, hash_password, verify_password
from app.auth.users import get_user
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
_DUMMY_HASH = hash_password("unknown-account-timing-placeholder")


def _throttled(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="Too many sign-in attempts. Try again shortly.",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/login", response_model=Token)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends()) -> Token:
    """Exchange username/password for a JWT bearer token."""
    # Trust only the ASGI peer, never a caller-provided forwarding header here.
    # (Behind a proxy, uvicorn sets the peer from X-Forwarded-For, but only for hops
    # listed in FORWARDED_ALLOW_IPS.)
    peer = request.client.host if request.client else "unknown"
    if retry_after := login_limiter.retry_after(peer):
        raise _throttled(retry_after)
    account = form.username.strip().lower()[:64]
    if retry_after := account_limiter.blocked_for(account):
        raise _throttled(retry_after)

    user = get_user(form.username)
    valid = verify_password(form.password, user.hashed_password if user else _DUMMY_HASH)
    if user is None or not valid or user.disabled:
        account_limiter.retry_after(account)  # count the failure against the account
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(username=user.username, role=user.role)
    return Token(
        access_token=token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=User)
async def read_me(current_user: User = Depends(get_current_user)) -> User:
    """Return the authenticated user's profile."""
    return current_user

"""FastAPI dependencies for authentication and role enforcement."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.auth.roles import Role
from app.auth.schemas import User
from app.auth.security import decode_access_token
from app.auth.users import get_user

# tokenUrl points at the login route so Swagger's "Authorize" button works.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Resolve and validate the current user from the bearer token."""
    token_data = decode_access_token(token)
    if token_data is None:
        raise _credentials_exc

    user = get_user(token_data.username)
    if user is None or user.disabled:
        raise _credentials_exc

    return User(username=user.username, role=user.role, disabled=user.disabled)


def require_roles(*allowed: Role) -> Callable[[User], User]:
    """Build a dependency that permits only the given roles.

    Usage::

        @router.get("/", dependencies=[Depends(require_roles(Role.ADMIN))])
    """
    allowed_set: set[Role] = set(allowed)

    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {sorted(r.value for r in allowed_set)}",
            )
        return user

    return _guard


def require_any(roles: Iterable[Role]) -> Callable[[User], User]:
    """Same as :func:`require_roles` but takes an iterable."""
    return require_roles(*roles)

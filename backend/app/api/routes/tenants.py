"""Tenant management — organisations, their policy and their membership.

Reading your own tenant is open to any signed-in user; creating tenants, editing
their policy and moving agents/users between them is an administrator action
(a platform-operator capability).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user, require_roles
from app.auth.roles import Role
from app.auth.schemas import User
from app.tenants.schemas import CreateTenantRequest, Tenant, TenantPolicy, TenantSummary
from app.tenants.store import TenantExists, get_tenant_store

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _summary_or_404(slug: str) -> TenantSummary:
    summary = get_tenant_store().summary(slug)
    if summary is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tenant '{slug}' not found.")
    return summary


@router.get("/me", response_model=TenantSummary)
def my_tenant(user: User = Depends(get_current_user)) -> TenantSummary:
    """The caller's own tenant — its policy and the agents/users it contains."""
    return _summary_or_404(user.tenant)


@router.get(
    "", response_model=list[TenantSummary], dependencies=[Depends(require_roles(Role.ADMIN))]
)
def list_tenants() -> list[TenantSummary]:
    """Every tenant (administrator / platform operator)."""
    store = get_tenant_store()
    return [store.summary(t.slug) for t in store.list_tenants()]  # type: ignore[misc]


@router.post(
    "",
    response_model=TenantSummary,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(Role.ADMIN))],
)
def create_tenant(body: CreateTenantRequest) -> TenantSummary:
    store = get_tenant_store()
    try:
        store.create_tenant(Tenant(slug=body.slug, name=body.name, policy=body.policy))
    except TenantExists as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _summary_or_404(body.slug)


@router.put(
    "/{slug}/policy",
    response_model=TenantSummary,
    dependencies=[Depends(require_roles(Role.ADMIN))],
)
def set_policy(slug: str, policy: TenantPolicy) -> TenantSummary:
    try:
        get_tenant_store().set_policy(slug, policy)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tenant '{slug}' not found.") from exc
    return _summary_or_404(slug)


@router.post(
    "/{slug}/agents/{agent}",
    response_model=TenantSummary,
    dependencies=[Depends(require_roles(Role.ADMIN))],
)
def assign_agent(slug: str, agent: str) -> TenantSummary:
    try:
        get_tenant_store().assign_agent(agent, slug)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tenant '{slug}' not found.") from exc
    return _summary_or_404(slug)


@router.post(
    "/{slug}/users/{username}",
    response_model=TenantSummary,
    dependencies=[Depends(require_roles(Role.ADMIN))],
)
def assign_user(slug: str, username: str) -> TenantSummary:
    try:
        get_tenant_store().assign_user(username, slug)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tenant '{slug}' not found.") from exc
    return _summary_or_404(slug)

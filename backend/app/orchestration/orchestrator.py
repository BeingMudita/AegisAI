"""The multi-agent orchestrator: delegation with tenant isolation and composed policy."""

from __future__ import annotations

from functools import lru_cache

from app.database.enums import SecurityEventType, SecuritySeverity
from app.orchestration.schemas import DelegationResult
from app.telemetry.store import get_audit_log
from app.tenants.store import TenantStore, get_tenant_store
from app.tools.gateway import ToolGateway, get_tool_gateway
from app.trust.engine import TrustEngine, get_trust_engine
from app.trust.scoring import TrustSignal


class MultiAgentOrchestrator:
    """Routes an action from one agent to another, within a tenant's guardrails."""

    def __init__(
        self,
        *,
        gateway: ToolGateway,
        trust: TrustEngine,
        tenants: TenantStore,
    ) -> None:
        self.gateway = gateway
        self.trust = trust
        self.tenants = tenants

    def delegate(
        self,
        *,
        caller: str,
        callee: str,
        tool: str,
        arguments: dict | None = None,
        session_id: str | None = None,
        depth: int = 1,
    ) -> DelegationResult:
        """``caller`` asks ``callee`` to run ``tool``. The delegation is allowed only
        within one tenant and within its delegation depth; the tool itself is then
        run as ``callee`` through the gateway, which enforces its effective policy."""
        caller_tenant = self.tenants.tenant_of_agent(caller)
        callee_tenant = self.tenants.tenant_of_agent(callee)

        def _deny(checkpoint: str, reason: str) -> DelegationResult:
            get_audit_log().record_event(
                event_type=SecurityEventType.POLICY_VIOLATION,
                severity=SecuritySeverity.HIGH,
                source="orchestration",
                agent=caller,
                session_id=session_id,
                description=f"Delegation {caller}→{callee} denied at {checkpoint}: {reason}",
                details={"callee": callee, "tool": tool, "checkpoint": checkpoint},
            )
            self.trust.observe_agent(
                caller,
                None,
                TrustSignal.POLICY_VIOLATION,
                rationale=f"Delegation to {callee} denied at {checkpoint}",
                session_id=session_id,
            )
            return DelegationResult(
                tenant=caller_tenant,
                caller=caller,
                callee=callee,
                tool=tool,
                allowed=False,
                reason=reason,
                checkpoint=checkpoint,
            )

        # 1. Tenant isolation — no cross-tenant delegation.
        if caller_tenant != callee_tenant:
            return _deny(
                "tenant",
                f"'{caller}' ({caller_tenant}) may not delegate to '{callee}' "
                f"({callee_tenant}): different tenants.",
            )

        # 2. Delegation depth within the tenant's limit.
        tenant = self.tenants.get_tenant(caller_tenant)
        max_depth = tenant.policy.max_delegation_depth if tenant else 1
        if depth > max_depth:
            return _deny(
                "depth", f"Delegation depth {depth} exceeds the tenant limit of {max_depth}."
            )

        # 3. The caller must not be suspended.
        standing = self.trust.evaluate_agent(caller, None, required=0.0, action="delegate")
        if not standing.allowed:
            return _deny("caller_standing", standing.reason)

        # 4. Run the tool AS the callee, with the caller as the principal so the
        #    callee's trust is scored for acting on this caller's behalf. The gateway
        #    enforces the callee's effective (tenant-composed) policy and the rest.
        result = self.gateway.execute(
            callee, tool, arguments, session_id=session_id, principal=caller
        )
        get_audit_log().log_decision(
            "orchestration",
            allowed=result.executed,
            subject=f"{callee}.{tool}",
            agent=caller,
            reason=f"Delegated {tool} to {callee}: {result.decision_reason}",
        )
        return DelegationResult(
            tenant=caller_tenant,
            caller=caller,
            callee=callee,
            tool=tool,
            allowed=True,  # the delegation was permitted; the tool outcome is in tool_result
            reason=f"Delegation permitted within tenant '{caller_tenant}'.",
            tool_result=result,
        )


@lru_cache
def get_orchestrator() -> MultiAgentOrchestrator:
    """The process-wide orchestrator."""
    return MultiAgentOrchestrator(
        gateway=get_tool_gateway(), trust=get_trust_engine(), tenants=get_tenant_store()
    )

"""Multi-agent orchestration — one agent delegating an action to another.

The orchestrator owns only the *delegation* decision: the caller and callee must
belong to the same tenant (isolation), the chain must stay within the tenant's
delegation depth, and the caller must not be suspended. The actual tool call then
goes through the ordinary :class:`~app.tools.gateway.ToolGateway`, so the callee's
effective (tenant-composed) policy, trust, DLP, firewall and approval all apply
unchanged — no security logic is duplicated here.
"""

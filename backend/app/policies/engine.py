"""The policy engine — answers 'what is this agent allowed to do?'

Pure evaluation logic over an :class:`AgentPolicy`. No I/O, so it is trivially
testable and can be fed policies loaded from the database, a YAML file, or the
example JSON store.

Decision rules:
  * A tool is allowed only if it is NOT in ``blocked_tools`` AND it appears in
    ``allowed_tools``. Block always wins over allow (deny-by-default).
  * A domain is allowed if it matches (or is a subdomain of) an entry in
    ``allowed_domains``. An empty ``allowed_domains`` means no domain is allowed.
  * A data category is sensitive if it appears in ``sensitive_data``.
"""

from __future__ import annotations

from app.policies.schemas import AgentAllowances, AgentPolicy, PolicyDecision


class PolicyEngine:
    """Evaluates actions against a single agent's policy."""

    def __init__(self, policy: AgentPolicy) -> None:
        self.policy = policy

    # ----------------------------------------------------------------- tools
    def can_use_tool(self, tool: str) -> PolicyDecision:
        """Decide whether the agent may use ``tool``."""
        agent = self.policy.agent
        if tool in self.policy.blocked_tools:
            return PolicyDecision(
                allowed=False,
                reason=f"Tool '{tool}' is explicitly blocked for {agent}.",
                agent=agent,
                subject=tool,
            )
        if tool in self.policy.allowed_tools:
            return PolicyDecision(
                allowed=True,
                reason=f"Tool '{tool}' is in the allow-list for {agent}.",
                agent=agent,
                subject=tool,
            )
        return PolicyDecision(
            allowed=False,
            reason=f"Tool '{tool}' is not in the allow-list for {agent} (deny by default).",
            agent=agent,
            subject=tool,
        )

    # --------------------------------------------------------------- domains
    def can_access_domain(self, domain: str) -> PolicyDecision:
        """Decide whether the agent may access ``domain`` (or a subdomain)."""
        agent = self.policy.agent
        host = domain.lower().strip()
        for allowed in self.policy.allowed_domains:
            allowed = allowed.lower().strip()
            if host == allowed or host.endswith("." + allowed):
                return PolicyDecision(
                    allowed=True,
                    reason=f"Domain '{domain}' matches allowed domain '{allowed}'.",
                    agent=agent,
                    subject=domain,
                )
        return PolicyDecision(
            allowed=False,
            reason=f"Domain '{domain}' is not in the allowed-domains for {agent}.",
            agent=agent,
            subject=domain,
        )

    # ------------------------------------------------------ sensitive data
    def is_sensitive(self, data_category: str) -> bool:
        """Return True if ``data_category`` is marked sensitive for this agent."""
        return data_category in self.policy.sensitive_data

    # -------------------------------------------------------------- summary
    def allowances(self) -> AgentAllowances:
        """Summarize everything the agent is allowed / restricted to do."""
        return AgentAllowances(
            agent=self.policy.agent,
            allowed_tools=list(self.policy.allowed_tools),
            blocked_tools=list(self.policy.blocked_tools),
            allowed_domains=list(self.policy.allowed_domains),
            sensitive_data=list(self.policy.sensitive_data),
        )

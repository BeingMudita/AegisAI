"""Tests for the policy engine and the example FinanceAgent policy."""

from app.policies.engine import PolicyEngine
from app.policies.schemas import AgentPolicy
from app.policies.store import get_policy


def _finance() -> PolicyEngine:
    policy = get_policy("FinanceAgent")
    assert policy is not None
    return PolicyEngine(policy)


def test_example_policy_loads() -> None:
    policy = get_policy("financeagent")  # case-insensitive
    assert policy is not None
    assert policy.agent == "FinanceAgent"
    assert "search_documents" in policy.allowed_tools
    assert "shell" in policy.blocked_tools


def test_allowed_tool() -> None:
    d = _finance().can_use_tool("search_documents")
    assert d.allowed is True


def test_blocked_tool_wins() -> None:
    d = _finance().can_use_tool("shell")
    assert d.allowed is False
    assert "blocked" in d.reason.lower()


def test_unknown_tool_denied_by_default() -> None:
    d = _finance().can_use_tool("delete_everything")
    assert d.allowed is False
    assert "deny by default" in d.reason.lower()


def test_block_overrides_allow() -> None:
    engine = PolicyEngine(
        AgentPolicy(
            agent="X",
            allowed_tools=["risky"],
            blocked_tools=["risky"],
        )
    )
    assert engine.can_use_tool("risky").allowed is False


def test_domain_and_subdomain() -> None:
    engine = _finance()
    assert engine.can_access_domain("company.com").allowed is True
    assert engine.can_access_domain("mail.company.com").allowed is True
    assert engine.can_access_domain("evil.com").allowed is False


def test_sensitive_data() -> None:
    engine = _finance()
    assert engine.is_sensitive("credentials") is True
    assert engine.is_sensitive("public_blog") is False


def test_allowances_summary() -> None:
    a = _finance().allowances()
    assert a.agent == "FinanceAgent"
    assert set(a.blocked_tools) == {"shell", "external_upload"}

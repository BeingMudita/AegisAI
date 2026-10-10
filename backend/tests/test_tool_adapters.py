"""Real (non-sandboxed) tool adapters behind the approval workflow.

The gateway picks a real adapter only when ``TOOL_EXECUTION_MODE=live``, and a
side-effecting adapter (email, upload, shell) runs live only after a human
approval. These tests pin that selection logic and the safety guards, and
exercise each adapter with its I/O monkeypatched so nothing leaves the machine.
"""

from __future__ import annotations

import smtplib

import pytest

from app.config import get_settings
from app.database.enums import ToolRequestStatus
from app.firewall.scanner import PromptFirewall
from app.policies.config import get_global_config
from app.tools import adapters
from app.tools.gateway import ToolGateway
from app.tools.sandbox import IMPLEMENTATIONS, ToolContext
from app.tools.schemas import ToolCallResult
from app.trust.engine import TrustEngine


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch the process-wide settings to live tool execution for one test."""
    monkeypatch.setattr(get_settings(), "tool_execution_mode", "live")


def _gateway() -> ToolGateway:
    return ToolGateway(config=get_global_config(), firewall=PromptFirewall(), trust=TrustEngine())


def _result(tool: str, **args: object) -> ToolCallResult:
    return ToolCallResult(agent="FinanceAgent", tool=tool, arguments=dict(args))


def _ctx() -> ToolContext:
    return ToolContext(agent="FinanceAgent")


# --------------------------------------------------------- adapter selection
def test_sandbox_is_the_default() -> None:
    gw = _gateway()
    run_fn, mode = gw._select_adapter(_result("send_email", to="cfo@company.com"),
                                      IMPLEMENTATIONS["send_email"])
    assert mode == "sandbox" and run_fn is IMPLEMENTATIONS["send_email"].run


def test_catalog_marks_live_capable_tools() -> None:
    capable = {t.name for t in _gateway().describe() if t.live_capable}
    assert capable == {"web_fetch", "send_email", "external_upload", "shell"}


def test_read_only_web_fetch_runs_live_without_approval(live: None) -> None:
    run_fn, mode = _gateway()._select_adapter(
        _result("web_fetch", url="https://company.com/news"), IMPLEMENTATIONS["web_fetch"]
    )
    assert mode == "live" and run_fn is adapters.web_fetch_live


def test_side_effecting_tool_is_refused_live_without_approval(live: None) -> None:
    from app.tools.gateway import _Denied

    with pytest.raises(_Denied) as exc:
        _gateway()._select_adapter(
            _result("send_email", to="cfo@company.com"), IMPLEMENTATIONS["send_email"]
        )
    assert exc.value.checkpoint == "execution"


def test_side_effecting_tool_runs_live_once_approved(live: None) -> None:
    approved = _result("send_email", to="cfo@company.com")
    approved.reviewed_by = "admin"  # came through the approval queue
    run_fn, mode = _gateway()._select_adapter(approved, IMPLEMENTATIONS["send_email"])
    assert mode == "live" and run_fn is adapters.send_email_live


def test_live_shell_stays_off_until_explicitly_enabled(
    live: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.gateway import _Denied

    approved = _result("shell", command="echo hi")
    approved.reviewed_by = "admin"
    with pytest.raises(_Denied, match="shell execution is disabled"):
        _gateway()._select_adapter(approved, IMPLEMENTATIONS["shell"])

    monkeypatch.setattr(get_settings(), "tool_shell_enable", True)
    run_fn, mode = _gateway()._select_adapter(approved, IMPLEMENTATIONS["shell"])
    assert mode == "live" and run_fn is adapters.shell_live


# ------------------------------------------------------------- the adapters
def test_web_fetch_live_reads_and_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapters, "_open", lambda req, timeout: (200, b"hello world"))
    out = adapters.web_fetch_live({"url": "https://company.com/news"}, _ctx())
    assert "HTTP 200" in out and "hello world" in out


def test_web_fetch_live_rejects_non_https() -> None:
    with pytest.raises(ValueError, match="https"):
        adapters.web_fetch_live({"url": "http://company.com/news"}, _ctx())


def test_web_fetch_live_returns_http_errors_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def _boom(req, timeout):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(adapters, "_open", _boom)
    assert "404" in adapters.web_fetch_live({"url": "https://company.com/missing"}, _ctx())


def test_send_email_live_unconfigured_fails_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    with pytest.raises(RuntimeError, match="not configured"):
        adapters.send_email_live({"to": "cfo@company.com", "body": "hi"}, _ctx())


def test_send_email_live_sends_over_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, object] = {}

    class _FakeSMTP:
        def __init__(self, host, port, timeout=0):  # type: ignore[no-untyped-def]
            sent["host"] = host
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self
        def __exit__(self, *a):  # type: ignore[no-untyped-def]
            return False
        def starttls(self, context=None):  # type: ignore[no-untyped-def]
            sent["tls"] = True
        def login(self, user, pwd):  # type: ignore[no-untyped-def]
            sent["login"] = user
        def send_message(self, msg):  # type: ignore[no-untyped-def]
            sent["to"] = msg["To"]

    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    monkeypatch.setattr(get_settings(), "smtp_from", "agent@aegis.local")
    monkeypatch.setattr(get_settings(), "smtp_username", "")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    out = adapters.send_email_live({"to": "cfo@company.com", "body": "report"}, _ctx())
    assert sent["to"] == "cfo@company.com" and sent.get("tls") is True
    assert "sent to cfo@company.com" in out


def test_external_upload_live_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapters, "_open", lambda req, timeout: (200, b"ok"))
    out = adapters.external_upload_live(
        {"url": "https://sink.example.com/u", "data": "payload"}, _ctx()
    )
    assert "Uploaded" in out and "HTTP 200" in out


def test_shell_live_runs_a_command() -> None:
    out = adapters.shell_live({"command": "echo aegis-shell-ok"}, _ctx())
    assert "aegis-shell-ok" in out and "exit 0" in out


# ----------------------------------------------------- end-to-end via gateway
def test_approved_email_runs_the_live_adapter(
    live: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline path: live mode, execute queues for approval, approval sends
    for real (SMTP monkeypatched)."""
    captured: dict[str, object] = {}

    class _FakeSMTP:
        def __init__(self, *a, **k):  # type: ignore[no-untyped-def]
            pass
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self
        def __exit__(self, *a):  # type: ignore[no-untyped-def]
            return False
        def starttls(self, context=None):  # type: ignore[no-untyped-def]
            pass
        def send_message(self, msg):  # type: ignore[no-untyped-def]
            captured["to"] = msg["To"]

    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    monkeypatch.setattr(get_settings(), "smtp_username", "")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    gw = _gateway()
    pending = gw.execute("FinanceAgent", "send_email", {"to": "cfo@company.com", "body": "Q3"})
    assert pending.status == ToolRequestStatus.PENDING  # not sent yet

    done = gw.approve(pending.id, "admin", "verified")
    assert done.status == ToolRequestStatus.EXECUTED
    assert captured["to"] == "cfo@company.com"
    assert any(c.checkpoint == "execution" and "live" in c.detail for c in done.checks)

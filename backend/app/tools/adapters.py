"""Real (non-sandboxed) tool adapters.

Each adapter has the same signature as its sandbox twin in ``sandbox.py`` —
``(arguments, ToolContext) -> str`` — but actually performs the action: a real
HTTP request, a real email over SMTP, a real shell command. They are selected by
the gateway only when ``TOOL_EXECUTION_MODE=live`` (see :mod:`app.config`), and a
*side-effecting* adapter (email, upload, shell) is reached only after a human has
approved the call — the gateway enforces that invariant, these functions assume it.

Everything here is standard-library only, to keep the project's "no new runtime
dependency" rule: ``urllib`` for HTTP, ``smtplib`` for mail, ``subprocess`` for
the shell. The gateway has already vetted the arguments before an adapter runs —
one allow-listed ``https`` destination, no injection payload, DLP applied to
outgoing free text — so an adapter validates only what defends it directly
(scheme, size, redirects, timeouts).
"""

from __future__ import annotations

import smtplib
import ssl
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import EmailMessage

from app.config import get_settings
from app.tools.sandbox import ToolContext, _require

RunFn = Callable[[dict, ToolContext], str]

_USER_AGENT = "AegisAI-ToolGateway/1.0"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n…[truncated at {limit} chars]"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: the gateway allow-listed one host, and a 3xx could hop off it."""

    def redirect_request(self, *args, **kwargs):  # type: ignore[override]
        return None


def _open(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(request, timeout=timeout) as response:
        max_bytes = get_settings().tool_http_max_bytes
        body = response.read(max_bytes + 1)
        return response.status, body


# --------------------------------------------------------------------- web_fetch
def web_fetch_live(args: dict, ctx: ToolContext) -> str:
    """Fetch a page over real HTTP (GET). Read-only; https only; no redirects."""
    settings = get_settings()
    url = _require(args, "url")
    if not url.lower().startswith("https://"):
        raise ValueError("web_fetch allows https URLs only.")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT}, method="GET")
    try:
        status, body = _open(request, settings.tool_http_timeout_seconds)
    except urllib.error.HTTPError as exc:  # a 4xx/5xx is a result, not a tool failure
        return f"{exc.code} {exc.reason}: {url}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Could not reach {url}: {exc}") from exc
    text = body[: settings.tool_http_max_bytes].decode("utf-8", errors="replace")
    note = " (truncated)" if len(body) > settings.tool_http_max_bytes else ""
    return f"HTTP {status}{note}\n{text}"


# -------------------------------------------------------------------- send_email
def send_email_live(args: dict, ctx: ToolContext) -> str:
    """Send a real email over SMTP. DLP has already redacted subject/body."""
    settings = get_settings()
    if not settings.smtp_host:
        raise RuntimeError("Live send_email is not configured: set SMTP_HOST (and SMTP_FROM).")
    to = _require(args, "to")
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_username or f"{ctx.agent}@aegis.local"
    message["To"] = to
    message["Subject"] = str(args.get("subject", "(no subject)"))
    message.set_content(str(args.get("body", "")))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise RuntimeError(f"SMTP send to {to} failed: {exc}") from exc
    return f"Email sent to {to} via {settings.smtp_host}."


# --------------------------------------------------------------- external_upload
def external_upload_live(args: dict, ctx: ToolContext) -> str:
    """POST a payload to an external https endpoint. DLP has redacted the data."""
    settings = get_settings()
    url = _require(args, "url")
    if not url.lower().startswith("https://"):
        raise ValueError("external_upload allows https URLs only.")
    payload = str(args.get("data", "")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"User-Agent": _USER_AGENT, "Content-Type": "application/octet-stream"},
        method="POST",
    )
    try:
        status, body = _open(request, settings.tool_http_timeout_seconds)
    except urllib.error.HTTPError as exc:
        return f"Upload to {url} returned {exc.code} {exc.reason}."
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Upload to {url} failed: {exc}") from exc
    detail = body[:200].decode("utf-8", errors="replace").strip()
    return f"Uploaded {len(payload)} bytes to {url} (HTTP {status}). {detail}".strip()


# --------------------------------------------------------------------- shell
def shell_live(args: dict, ctx: ToolContext) -> str:
    """Run a shell command. Reached only when TOOL_SHELL_ENABLE is set AND the call
    was approved — the gateway guards both; this just executes with a timeout."""
    command = _require(args, "command")
    try:
        proc = subprocess.run(
            command,
            shell=True,  # noqa: S602 — real shell execution is the whole point of this tool
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {exc.timeout}s.") from exc
    out = (proc.stdout or "") + (proc.stderr or "")
    limit = get_settings().tool_http_max_bytes
    return _truncate(f"[exit {proc.returncode}]\n{out}".rstrip(), limit)


#: Tool name → real adapter. Tools without an entry (search_documents,
#: read_database, generate_report) have no "live" form — they are internal and
#: always use their sandbox implementation.
LIVE_ADAPTERS: dict[str, RunFn] = {
    "web_fetch": web_fetch_live,
    "send_email": send_email_live,
    "external_upload": external_upload_live,
    "shell": shell_live,
}

#: Live adapters that cause an external, irreversible effect. These may run live
#: only after human approval; web_fetch (read-only GET) is not in this set.
SIDE_EFFECTING: frozenset[str] = frozenset({"send_email", "external_upload", "shell"})

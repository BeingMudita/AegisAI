"""The ``aegis`` command-line tool.

    aegis init                 # write a starter aegis.yaml
    aegis scan [path]          # validate a policy file / screen a prompt
    aegis redteam              # run the attack suites against a sandbox
    aegis serve                # start the security gateway (REST API)
    aegis inspect              # open the operator dashboard

Stdlib-only (argparse) so it adds no dependency.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import webbrowser
from pathlib import Path

from app.config import get_settings


def _cmd_init(args: argparse.Namespace) -> int:
    from app.platform.policyfile import sample_yaml

    path = Path(args.path)
    if path.exists() and not args.force:
        print(f"{path} already exists. Use --force to overwrite.")
        return 1
    path.write_text(sample_yaml(args.agent), encoding="utf-8")
    print(f"Wrote {path} for agent '{args.agent}'.")
    print("Edit it, then run:  aegis scan")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    from app.platform.policyfile import PolicyFileError, load_aegis_file

    try:
        file = load_aegis_file(args.path)
    except PolicyFileError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    posture = file.apply()
    print(f"✓ {args.path} is valid — resolved posture for '{posture.agent}':")
    print(f"    tools      : {', '.join(posture.allowed_tools) or '(none)'}")
    print(f"    domains    : {', '.join(posture.allowed_domains) or '(none)'}")
    print(f"    sensitive  : {', '.join(posture.sensitive_data) or '(none)'}")
    print(f"    trust min  : {posture.trust_minimum}")
    print(f"    approval   : {', '.join(posture.approval_required) or '(none)'}")
    for warning in posture.warnings:
        print(f"    ⚠ {warning}")

    if args.prompt is not None:
        from app.firewall.scanner import get_firewall

        verdict = get_firewall().scan(args.prompt)
        print()
        print(f"Prompt firewall: {verdict.action.value}  (score {verdict.score:.2f})")
        print(f"    {verdict.reason}")
        if verdict.action.value == "BLOCK":
            return 2
    return 0


def _cmd_redteam(args: argparse.Namespace) -> int:
    from app.redteam.service import get_redteam_service

    suites = [s.strip() for s in args.suite.split(",") if s.strip()]
    print(f"Running red-team suites {suites} against an isolated sandbox…")
    run = get_redteam_service().start(suites, started_by="cli", wait=True)
    if run.status != "completed":
        print(f"✗ Run {run.status}: {run.error or ''}", file=sys.stderr)
        return 1
    if run.firewall:
        fw = run.firewall
        print(
            f"Firewall : recall {fw.recall:.1%} · precision {fw.precision:.1%} · "
            f"false-alarm {fw.false_positive_rate:.1%}  ({fw.cases} cases)"
        )
    if run.agents:
        ag = run.agents
        print(f"Agents   : {ag.passed}/{ag.scenarios} scenarios defended end to end")
    ok = (not run.agents or run.agents.passed == run.agents.scenarios)
    return 0 if ok else 2


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    print(f"Starting the AegisAI gateway on http://{args.host}:{args.port}  (POST /v1/secure/chat)")
    if not settings.aegis_api_key and not settings.is_production:
        print("  (dev mode: no AEGIS_API_KEY set — the gateway is open locally)")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    url = args.url or get_settings().dashboard_url
    print(f"Opening the AegisAI dashboard: {url}")
    with contextlib.suppress(Exception):  # headless environments just get the URL printed
        webbrowser.open(url)
    return 0


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="aegis", description="AegisAI — a zero-trust security layer for AI agents."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="write a starter aegis.yaml")
    p_init.add_argument("--path", default=settings.aegis_policy_path)
    p_init.add_argument("--agent", default="FinanceAgent")
    p_init.add_argument("--force", action="store_true", help="overwrite an existing file")
    p_init.set_defaults(func=_cmd_init)

    p_scan = sub.add_parser("scan", help="validate a policy file and/or screen a prompt")
    p_scan.add_argument("path", nargs="?", default=settings.aegis_policy_path)
    p_scan.add_argument("--prompt", default=None, help="screen this text through the firewall")
    p_scan.set_defaults(func=_cmd_scan)

    p_rt = sub.add_parser("redteam", help="run the attack suites against a sandbox")
    p_rt.add_argument("--suite", default="firewall,agents", help="comma-separated: firewall,agents")
    p_rt.set_defaults(func=_cmd_redteam)

    p_serve = sub.add_parser("serve", help="start the security gateway (REST API)")
    p_serve.add_argument("--host", default=settings.api_host)
    p_serve.add_argument("--port", type=int, default=settings.api_port)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    p_inspect = sub.add_parser("inspect", help="open the operator dashboard")
    p_inspect.add_argument("--url", default=None)
    p_inspect.set_defaults(func=_cmd_inspect)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

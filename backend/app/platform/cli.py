"""The ``aegis`` command-line tool — the security lifecycle.

    aegis audit <target>       # SCAN: profile an agent and score it /100
    aegis generate-policy <t>  # GENERATE: least-privilege aegis.yaml
    aegis policy test [path]    # TEST: run the red-team against a policy
    aegis policy validate [p]   #        validate an aegis.yaml
    aegis scan-agent <dir>     # alias: audit a source directory
    aegis init                 # write a starter aegis.yaml
    aegis scan [path]          # validate a policy file / screen a prompt
    aegis redteam              # run the attack suites against a sandbox
    aegis serve                # PROTECT: start the security gateway
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
    run = get_redteam_service().start(suites, started_by="cli", wait=True)  # type: ignore[arg-type]
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


# --------------------------------------------------------------- scanner
_CLI_ORDER = [
    "Prompt Injection",
    "Indirect Injection",
    "Excessive Tool Permission",
    "Sensitive Data Exposure",
    "Unsafe External Destinations",
    "Missing Human Approval",
    "Output Leakage",
]
_SEV_MARK = {"LOW": "✓", "MEDIUM": "⚠", "HIGH": "✗"}  # ✓ ⚠ ✗


def _print_report(report) -> None:  # report: SecurityReport
    p = report.profile
    print(f"AegisAI Security Report — {report.agent}")
    print(f"    discovered via {p.source} · LLM: {p.llm}")
    print()
    print(f"    AGENT SECURITY SCORE   {report.score} / 100   ({report.grade})")
    print("    " + "-" * 44)
    by = {f.category: f for f in report.findings}
    for cat in _CLI_ORDER:
        f = by.get(cat)
        if f:
            print(f"    {cat:<30} {_SEV_MARK[f.severity]} {f.severity}")

    fixes = [f for f in report.findings if f.fix and f.severity != "LOW"]
    if fixes:
        print("\n    Recommended fixes")
        for f in fixes:
            print(f"    {_SEV_MARK[f.severity]} {f.category}: {f.detail}")
            for line in f.fix.splitlines():
                print(f"        {line}")

    print("\n    Permission profile")
    print(f"      {report.agent}  (LLM: {p.llm})")
    if p.tools:
        print("      Tools:")
        for t in p.tools:
            flags = [t.risk_level]
            if t.external:
                flags.append(f"external:{t.domain_kind or 'url'}")
            if t.requires_approval:
                flags.append("approval")
            print(f"        - {t.name}  [{' · '.join(flags)}]")
    if p.data_sources:
        print("      Data sources:")
        for d in p.data_sources:
            print(f"        - {d.name}" + ("  (untrusted)" if d.untrusted else ""))
    if p.data_flows:
        print("      Data flows:")
        for fl in p.data_flows:
            print(f"        - {fl.label}  [{fl.risk}]")
    if p.notes:
        print("\n    Notes")
        for n in p.notes:
            print(f"      - {n}")


def _cmd_audit(args: argparse.Namespace) -> int:
    from app.platform import scanner

    try:
        report = scanner.audit(args.target)
    except scanner.ScannerError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    if args.json:
        import json

        print(json.dumps(report.model_dump(), indent=2, default=str))
    else:
        _print_report(report)
    if args.html:
        Path(args.html).write_text(scanner.render_html(report), encoding="utf-8")
        print(f"\nHTML report written to {args.html}")
    return 0


def _cmd_generate_policy(args: argparse.Namespace) -> int:
    from app.platform import scanner

    try:
        profile = scanner.profile_target(args.target)
    except scanner.ScannerError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    yaml_text = scanner.generate_policy(profile).to_yaml()
    if args.out:
        Path(args.out).write_text(yaml_text, encoding="utf-8")
        print(f"Wrote generated policy to {args.out}  (agent: {profile.name})")
        print(f"Next:  aegis policy test {args.out}")
    else:
        print(yaml_text)
    return 0


def _cmd_policy_validate(args: argparse.Namespace) -> int:
    from app.platform.policyfile import PolicyFileError, load_aegis_file

    try:
        file = load_aegis_file(args.path)
    except PolicyFileError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(f"✓ {args.path} is a valid aegis.yaml (agent: {file.agent.name}).")
    for warning in file.lint():
        print(f"  ⚠ {warning}")
    return 0


def _cmd_policy_test(args: argparse.Namespace) -> int:
    from app.platform import scanner
    from app.platform.policyfile import PolicyFileError, load_aegis_file
    from app.redteam.service import get_redteam_service

    try:
        file = load_aegis_file(args.path)
    except PolicyFileError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    file.apply()
    agent = file.agent.name
    report = scanner.audit(args.path)
    print(f"Policy '{agent}' — security score {report.score}/100 ({report.grade}).")
    suites = [s.strip() for s in args.suite.split(",") if s.strip()]
    print(f"Running red-team {suites} against an isolated sandbox…")
    run = get_redteam_service().start(suites, started_by="cli", wait=True)  # type: ignore[arg-type]
    if run.status != "completed":
        print(f"✗ Run {run.status}: {run.error or ''}", file=sys.stderr)
        return 1
    failed = []
    if run.agents:
        mine = [s for s in run.agents.results if s.agent == agent]
        passed = sum(1 for s in mine if s.passed)
        print(f"Agent scenarios for {agent}: {passed}/{len(mine)} defended")
        for s in mine:
            print(f"  {'✓' if s.passed else '✗'} {s.id} {s.title}")
        failed = [s for s in mine if not s.passed]
    if run.firewall:
        fw = run.firewall
        print(f"Firewall: recall {fw.recall:.1%} · precision {fw.precision:.1%}")
    return 0 if not failed else 2


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="aegis", description="AegisAI — a zero-trust security layer for AI agents."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="profile an agent and score its security /100")
    p_audit.add_argument("target", help="agent name | aegis.yaml | source directory")
    p_audit.add_argument("--json", action="store_true", help="emit the full report as JSON")
    p_audit.add_argument("--html", default=None, metavar="FILE", help="also write an HTML report")
    p_audit.set_defaults(func=_cmd_audit)

    p_scan_agent = sub.add_parser("scan-agent", help="audit an agent source directory")
    p_scan_agent.add_argument("target", help="path to the agent's source directory")
    p_scan_agent.add_argument("--json", action="store_true")
    p_scan_agent.add_argument("--html", default=None, metavar="FILE")
    p_scan_agent.set_defaults(func=_cmd_audit)

    p_gen = sub.add_parser("generate-policy", help="generate a least-privilege aegis.yaml")
    p_gen.add_argument("target", help="agent name | aegis.yaml | source directory")
    p_gen.add_argument("--out", default=None, metavar="FILE", help="write to a file (else stdout)")
    p_gen.set_defaults(func=_cmd_generate_policy)

    p_policy = sub.add_parser("policy", help="validate or test an aegis.yaml")
    psub = p_policy.add_subparsers(dest="policy_cmd", required=True)
    pv = psub.add_parser("validate", help="validate an aegis.yaml and lint it")
    pv.add_argument("path", nargs="?", default=settings.aegis_policy_path)
    pv.set_defaults(func=_cmd_policy_validate)
    pt = psub.add_parser("test", help="apply a policy and run the red-team against it")
    pt.add_argument("path", nargs="?", default=settings.aegis_policy_path)
    pt.add_argument("--suite", default="agents", help="comma-separated: firewall,agents")
    pt.set_defaults(func=_cmd_policy_test)

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

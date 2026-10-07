"""The ``aegis`` command-line tool.

    aegis init                 # write a starter aegis.yaml
    aegis scan [path]          # validate a policy file / screen a prompt
    aegis redteam              # run the attack suites against a sandbox
    aegis serve                # start the security gateway (REST API)
    aegis inspect              # open the operator dashboard
    aegis verify-models        # check the configured models against their pins
    aegis aibom [-o file]      # the pinned models as a CycloneDX AI-BOM
    aegis retention            # expire idle sessions, delete data past retention

Stdlib-only (argparse) so it adds no dependency.
"""

from __future__ import annotations

import argparse
import contextlib
import json
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


def _cmd_verify_models(args: argparse.Namespace) -> int:
    from app.agents.brain import OllamaClient
    from app.supply_chain.provenance import (
        ProvenanceError,
        check_ollama,
        provenance_mode,
        recent_checks,
        verified_huggingface_path,
    )

    settings = get_settings()
    print(f"Model provenance mode: {provenance_mode()}")
    if settings.embedding_backend.lower() != "hashing":
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            print(f"- {settings.embedding_model}: sentence-transformers not installed, skipped")
        else:
            with contextlib.suppress(ProvenanceError):  # recorded; reported below
                verified_huggingface_path(settings.embedding_model)
    if settings.llm_backend.lower() != "rule_based":
        client = OllamaClient(
            settings.ollama_base_url, settings.model_name, settings.ollama_timeout
        )
        installed = client.installed_digests()
        if installed is None:
            print(f"- {client.model}: Ollama not reachable at {client.base_url}, skipped")
        else:
            check_ollama(client.model, installed)

    checks = recent_checks()
    for check in checks:
        mark = "OK  " if check.status == "verified" else "FAIL" if not check.allowed else "WARN"
        print(f"{mark} [{check.kind}] {check.name}: {check.status} - {check.detail}")
    return 0 if all(c.allowed for c in checks) else 1


def _cmd_aibom(args: argparse.Namespace) -> int:
    from app.supply_chain.aibom import build_aibom
    from app.supply_chain.manifest import get_manifest

    text = json.dumps(build_aibom(get_manifest()), indent=2) + "\n"
    if args.output in (None, "-"):
        sys.stdout.write(text)
    else:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    return 0


def _cmd_retention(args: argparse.Namespace) -> int:
    from app.retention import run_retention

    report = run_retention()
    if report.skipped:
        print("Another worker is running retention; nothing done.")
        return 0
    print(f"Expired idle sessions : {report.expired_sessions}")
    print(f"Deleted ended sessions: {report.purged_sessions}")
    print(f"Deleted audit events  : {report.purged_events}")
    print(f"Deleted budget rows   : {report.purged_usage_rows}")
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

    p_verify = sub.add_parser("verify-models", help="check the configured models' pins")
    p_verify.set_defaults(func=_cmd_verify_models)

    p_aibom = sub.add_parser("aibom", help="print the pinned models as a CycloneDX AI-BOM")
    p_aibom.add_argument("-o", "--output", default=None, help="output file (default: stdout)")
    p_aibom.set_defaults(func=_cmd_aibom)

    p_ret = sub.add_parser("retention", help="expire idle sessions and delete expired data")
    p_ret.set_defaults(func=_cmd_retention)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

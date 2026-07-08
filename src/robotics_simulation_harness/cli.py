from __future__ import annotations

import argparse
import os
import platform
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import __version__
from .evidence import make_evidence
from .guard import enforce_execution_guard
from .resolver import resolve_composition
from .yaml_io import read_yaml_or_json, write_json

console = Console()


def cmd_doctor(_args: argparse.Namespace) -> int:
    table = Table(title="robotics-simulation-harness")
    table.add_column("Item")
    table.add_column("Value")
    table.add_row("harness", __version__)
    table.add_row("python", platform.python_version())
    table.add_row("platform", platform.platform())
    table.add_row("cwd", os.getcwd())
    console.print(table)
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    resolved, trace = resolve_composition(Path(args.composition).resolve())
    if args.dry_run:
        console.print_json(data=resolved)
        console.print_json(data={"trace": trace})
        return 0
    write_json(Path(args.output), resolved)
    write_json(Path(args.trace), {"trace": trace})
    console.print(f"resolved: {args.output}")
    console.print(f"trace: {args.trace}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    scenario_path = Path(args.scenario).resolve()
    scenario = read_yaml_or_json(scenario_path)
    checks: list[dict[str, str]] = []
    try:
        enforce_execution_guard(scenario)
        checks.append({"name": "execution_guard", "result": "pass"})
        if args.dry_run:
            checks.append({"name": "dry_run", "result": "pass"})
            result = "pass"
        else:
            checks.append({"name": "process_execution", "result": "skip"})
            result = "pass"
    except Exception as exc:
        checks.append({"name": "execution_guard", "result": "fail", "message": str(exc)})
        result = "fail"

    evidence = make_evidence(
        run_id=args.run_id,
        scenario_path=scenario_path,
        scenario=scenario,
        result=result,
        checks=checks,
    )
    write_json(Path(args.evidence), evidence)
    console.print(f"evidence: {args.evidence}")
    return 0 if result == "pass" else 2


def cmd_status(_args: argparse.Namespace) -> int:
    console.print("status: no managed process registry in v0.1")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    reports = Path("artifacts/reports")
    if not reports.exists():
        console.print("logs: artifacts/reports does not exist")
        return 0
    for path in sorted(reports.glob("*.txt")):
        console.rule(str(path))
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-args.tail :]:
            console.print(line)
    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    console.print("stop: no managed process registry in v0.1")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="robotics-harness")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    scenario = sub.add_parser("scenario")
    scenario_sub = scenario.add_subparsers(dest="scenario_command", required=True)
    resolve = scenario_sub.add_parser("resolve")
    resolve.add_argument("--composition", required=True)
    resolve.add_argument("--output", default="artifacts/reports/resolved-scenario.json")
    resolve.add_argument("--trace", default="artifacts/reports/resolution-trace.json")
    resolve.add_argument("--dry-run", action="store_true")
    resolve.set_defaults(func=cmd_resolve)

    run = sub.add_parser("run")
    run.add_argument("--scenario", required=True)
    run.add_argument("--evidence", default="artifacts/reports/evidence-manifest.json")
    run.add_argument("--run-id", default="local-dry-run")
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)

    logs = sub.add_parser("logs")
    logs.add_argument("--tail", type=int, default=80)
    logs.set_defaults(func=cmd_logs)

    stop = sub.add_parser("stop")
    stop.set_defaults(func=cmd_stop)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

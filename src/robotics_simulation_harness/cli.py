from __future__ import annotations

import argparse
import hashlib
import os
import platform
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from . import __version__
from .evidence import file_sha256, make_evidence, write_json
from .guard import ExecutionGuardError, enforce_execution_guard
from .launching import LaunchError, build_launch_plan
from .process import ProcessGroupRunner
from .registry import ProcessRegistry, registry_path, stop_registry_entry
from .resolver import resolve_composition
from .ros_observer import RosObserverError, observe_ros_graph
from .schemas import (
    SchemaValidationError,
    validate_composition,
    validate_evidence,
    validate_scenario,
)
from .signal_coordinator import SignalCoordinator
from .yaml_io import read_yaml_or_json
from .yaml_io import write_json as write_yaml_json

console = Console()


def _runs_root() -> Path:
    return Path(os.environ.get("ROBOTICS_RUNS_ROOT", "runs")).resolve()


def _default_digest() -> str:
    return os.environ.get(
        "ROBOTICS_INFRA_IMAGE_DIGEST",
        "sha256:e7a30ca835e0419b929658b4d540aa1ec347b28a65bf1e9357f7d46793fa07ac",
    )


def _stack_lock_sha() -> str:
    lock_path = os.environ.get("ROBOTICS_STACK_LOCK_PATH")
    if lock_path:
        return file_sha256(Path(lock_path))
    return hashlib.sha256(b"foundation-stack-lock-placeholder").hexdigest()


def _allocate_domain_id(run_id: str) -> int:
    return int(hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:8], 16) % 100 + 1


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
    composition_path = Path(args.composition).resolve()
    composition = read_yaml_or_json(composition_path)
    validate_composition(composition)
    resolved, trace = resolve_composition(composition_path)
    validate_scenario(resolved)
    if args.dry_run:
        console.print_json(data=resolved)
        console.print_json(data={"trace": trace})
        return 0
    write_yaml_json(Path(args.output), resolved)
    write_yaml_json(Path(args.trace), {"trace": trace})
    console.print(f"resolved: {args.output}")
    console.print(f"trace: {args.trace}")
    return 0


def _append_check(checks: list[dict[str, str]], name: str, result: str, message: str = "") -> None:
    item = {"name": name, "result": result}
    if message:
        item["message"] = message
    checks.append(item)


def cmd_run(args: argparse.Namespace) -> int:
    scenario_path = Path(args.scenario).resolve()
    run_id = args.run_id
    runs_root = _runs_root()
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.evidence:
        evidence_path = Path(args.evidence).resolve()
    else:
        evidence_path = run_dir / "evidence-manifest.json"
    checks: list[dict[str, str]] = []
    result = "error"
    scenario: dict[str, Any] = {}
    ros_domain_id = _allocate_domain_id(run_id)
    registry = ProcessRegistry(registry_path(run_id, runs_root))

    try:
        scenario = read_yaml_or_json(scenario_path)
        validate_scenario(scenario)
        _append_check(checks, "schema_validation", "pass")
        enforce_execution_guard(scenario)
        _append_check(checks, "execution_guard", "pass")

        if args.dry_run:
            _append_check(checks, "dry_run", "pass")
            result = "pass"
        else:
            plan = build_launch_plan(scenario)
            coordinator = SignalCoordinator()
            runner = ProcessGroupRunner(coordinator)
            log_path = run_dir / "process.log"
            process = runner.run(
                plan.command,
                cwd=Path.cwd(),
                wall_timeout_sec=int(scenario["simulation"]["wall_timeout_sec"]),
                log_path=log_path,
            )
            if runner.process is not None:
                pgid = runner.process.pid
                if os.name == "posix":
                    try:
                        pgid = os.getpgid(runner.process.pid)
                    except ProcessLookupError:
                        pgid = runner.process.pid
                registry.write(
                    {
                        "run_id": run_id,
                        "pid": runner.process.pid,
                        "pgid": pgid,
                        "scenario_id": scenario["scenario_id"],
                        "command": plan.command,
                        "state": "exited",
                    }
                )
            _append_check(checks, "process_execution", "executed")
            if process.timed_out:
                _append_check(checks, "process_timeout", "fail", "wall timeout exceeded")
                result = "fail"
            elif process.stopped_by_signal:
                _append_check(checks, "process_signal", "fail", "stopped by signal")
                result = "fail"
            elif process.returncode != 0:
                _append_check(
                    checks,
                    "process_exit",
                    "fail",
                    f"command exited with {process.returncode}",
                )
                result = "fail"
            else:
                _append_check(checks, "process_exit", "pass")
                if os.environ.get("ROBOTICS_SKIP_ROS_OBSERVER") == "1":
                    _append_check(checks, "graph_ready", "pass", "observer skipped by env")
                    result = "pass"
                else:
                    try:
                        observation = observe_ros_graph(
                            scenario["expected_ros_graph"],
                            wall_timeout_sec=int(
                                scenario["expected_ros_graph"]["graph_ready_timeout_sec"]
                            ),
                        )
                        _append_check(
                            checks,
                            "graph_ready",
                            "pass" if observation.ok else "fail",
                            observation.message,
                        )
                        result = "pass" if observation.ok else "fail"
                    except RosObserverError as exc:
                        _append_check(checks, "graph_ready", "fail", str(exc))
                        result = "fail"
    except (SchemaValidationError, ExecutionGuardError, LaunchError) as exc:
        _append_check(checks, "preflight", "fail", str(exc))
        result = "fail"
    except Exception as exc:  # noqa: BLE001 - evidence must capture unexpected failures
        _append_check(checks, "runtime_error", "fail", str(exc))
        result = "error"
    finally:
        if not scenario:
            scenario = {
                "scenario_id": "unknown",
                "recording": {
                    "retention": {"mode": "on_failure", "ttl_days": 1, "lifecycle_tag": "error"}
                },
            }
            if not scenario_path.exists():
                scenario_path.write_text("{}", encoding="utf-8")
        evidence = make_evidence(
            run_id=run_id,
            scenario_path=scenario_path,
            scenario=scenario,
            result=result,
            checks=checks,
            ros_domain_id=ros_domain_id,
            stack_lock_sha256=_stack_lock_sha(),
            infra_image_digest=_default_digest(),
            signed=False,
            business_repo=None,
        )
        try:
            validate_evidence(evidence)
        except SchemaValidationError as exc:
            console.print(f"evidence schema warning: {exc}")
        write_json(evidence_path, evidence)
        console.print(f"evidence: {evidence_path}")
        if result != "pass" or args.dry_run:
            registry.clear()

    return 0 if result == "pass" else 2


def cmd_status(args: argparse.Namespace) -> int:
    runs_root = _runs_root()
    run_id = args.run_id
    entry = ProcessRegistry(registry_path(run_id, runs_root)).read()
    if entry is None:
        console.print(f"status: no managed process for run_id={run_id}")
        return 0
    console.print_json(data=entry)
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    runs_root = _runs_root()
    log_path = runs_root / args.run_id / "process.log"
    if not log_path.exists():
        console.print(f"logs: missing {log_path}")
        return 0
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-args.tail :]:
        console.print(line)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    runs_root = _runs_root()
    registry = ProcessRegistry(registry_path(args.run_id, runs_root))
    entry = registry.read()
    if entry is None:
        console.print(f"stop: no managed process for run_id={args.run_id}")
        return 0
    stop_registry_entry(entry)
    registry.clear()
    console.print(f"stop: terminated run_id={args.run_id}")
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
    resolve.add_argument("--output", default="runs/local/resolved-scenario.json")
    resolve.add_argument("--trace", default="runs/local/resolution-trace.json")
    resolve.add_argument("--dry-run", action="store_true")
    resolve.set_defaults(func=cmd_resolve)

    run = sub.add_parser("run")
    run.add_argument("--scenario", required=True)
    run.add_argument("--evidence", default="")
    run.add_argument("--run-id", required=True)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status")
    status.add_argument("--run-id", required=True)
    status.set_defaults(func=cmd_status)

    logs = sub.add_parser("logs")
    logs.add_argument("--run-id", required=True)
    logs.add_argument("--tail", type=int, default=80)
    logs.set_defaults(func=cmd_logs)

    stop = sub.add_parser("stop")
    stop.add_argument("--run-id", required=True)
    stop.set_defaults(func=cmd_stop)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

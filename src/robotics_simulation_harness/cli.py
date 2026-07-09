from __future__ import annotations

import argparse
import hashlib
import json
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


# A well-formed but unambiguous "no real image" sentinel. Evidence always
# requires `infra_image_digest` (even a dry-run or a non-container
# `external_command`/`ros2_launch` scenario has to satisfy the schema), but
# this must never be a specific-looking, plausible-but-fake sha256 like the
# hardcoded default it replaces: that silently made release evidence claim a
# tested image that was never actually built for the run it describes.
_NO_IMAGE_DIGEST_SENTINEL = "sha256:" + "0" * 64


class MissingDigestError(RuntimeError):
    pass


def _resolve_infra_image_digest(entrypoint: str | None) -> str:
    digest = os.environ.get("ROBOTICS_INFRA_IMAGE_DIGEST")
    if digest:
        return digest
    if entrypoint == "docker_compose":
        # A `docker_compose` scenario always launches a real, specific
        # container image. Fabricating its digest is exactly the "fake
        # release evidence" failure mode this must fail closed against
        # instead: refuse to run rather than lie about what was tested.
        raise MissingDigestError(
            "ROBOTICS_INFRA_IMAGE_DIGEST is required for docker_compose runs; "
            "refusing to fabricate the tested image digest in evidence"
        )
    return _NO_IMAGE_DIGEST_SENTINEL


def _stack_lock_sha() -> str:
    lock_path = os.environ.get("ROBOTICS_STACK_LOCK_PATH")
    if lock_path:
        return file_sha256(Path(lock_path))
    return hashlib.sha256(b"foundation-stack-lock-placeholder").hexdigest()


def _allocate_domain_id(run_id: str) -> int:
    return int(hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:8], 16) % 100 + 1


def _resolve_business_repo(args: argparse.Namespace) -> dict[str, Any] | None:
    """Identify the "business" repo/commit this run is testing on behalf of.

    Explicit `--business-repo-*` flags win; otherwise fall back to the
    ambient `GITHUB_*` env vars every GitHub Actions job already exports, so
    CI callers (harness's own CI, and infra's cross-repo gate) get a
    non-null `business_repo` for free without extra wiring. Returns `None`
    only when neither source has enough information, matching the schema's
    `business_repo: null` for purely local/manual runs.
    """
    url = getattr(args, "business_repo_url", "") or os.environ.get("ROBOTICS_BUSINESS_REPO_URL", "")
    commit = getattr(args, "business_repo_commit", "") or os.environ.get(
        "ROBOTICS_BUSINESS_REPO_COMMIT", ""
    )
    if not url and not commit:
        server = os.environ.get("GITHUB_SERVER_URL")
        repository = os.environ.get("GITHUB_REPOSITORY")
        sha = os.environ.get("GITHUB_SHA")
        if server and repository and sha:
            url, commit = f"{server}/{repository}", sha
    if not url or not commit:
        return None
    if getattr(args, "business_repo_dirty", False):
        dirty = True
    else:
        dirty_env = os.environ.get("ROBOTICS_BUSINESS_REPO_DIRTY", "")
        dirty = dirty_env.strip().lower() in {"1", "true", "yes"}
    return {"url": url, "commit": commit, "dirty": dirty}


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


_COMPOSE_ENV_KEYS = (
    "COMPOSE_PROJECT_NAME",
    "ROS_DOMAIN_ID",
    "RUN_ID",
    "FASTRTPS_DEFAULT_PROFILES_FILE",
    "RMW_IMPLEMENTATION",
    "IMAGE_TAG",
)


def _compose_env_snapshot() -> dict[str, str]:
    # `stop`/`docker compose down` must reproduce the exact env `start` used
    # to launch the stack (notably `COMPOSE_PROJECT_NAME` and the required
    # `ROS_DOMAIN_ID`), or it either tears down the wrong (default) project
    # or fails outright. Persist it in the registry entry instead of relying
    # on `stop`'s own ambient environment, which is very often a different
    # shell/process entirely.
    return {key: os.environ[key] for key in _COMPOSE_ENV_KEYS if key in os.environ}


def _check_embedded_graph_result(
    extra_artifacts: list[dict[str, Any]],
) -> tuple[str, str]:
    """Read the embedded in-network observer's result file from disk.

    `ROBOTICS_GRAPH_CHECK_EMBEDDED=1` means a sibling process/container
    already performed the live rclpy graph check and wrote its verdict to
    `ROBOTICS_GRAPH_OBSERVED_PATH`. Trusting the launch command's exit code
    alone would also pass if that sibling silently never ran (or crashed
    before writing anything); this must fail closed on any of those cases
    instead of ever inferring `graph_ready: pass` from process_exit alone.
    """
    observed_path_str = os.environ.get("ROBOTICS_GRAPH_OBSERVED_PATH")
    if not observed_path_str:
        return "fail", "ROBOTICS_GRAPH_CHECK_EMBEDDED=1 requires ROBOTICS_GRAPH_OBSERVED_PATH"
    observed_path = Path(observed_path_str)
    if not observed_path.is_file():
        return "fail", f"embedded observer result missing: {observed_path}"
    try:
        observed_sha = file_sha256(observed_path)
        observed = json.loads(observed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "fail", f"embedded observer result unreadable: {exc}"
    extra_artifacts.append(
        {
            "name": "graph-observed",
            "uri": str(observed_path),
            "sha256": observed_sha,
            "bytes": observed_path.stat().st_size,
        }
    )
    message = str(observed.get("message", "")) or "embedded observer result"
    if observed.get("ok") is True:
        return "pass", f"{message} (graph-observed sha256={observed_sha})"
    return "fail", f"{message} (graph-observed sha256={observed_sha})"


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
    extra_artifacts: list[dict[str, Any]] = []
    result = "error"
    scenario: dict[str, Any] = {}
    infra_image_digest = _NO_IMAGE_DIGEST_SENTINEL
    env_domain = os.environ.get("ROS_DOMAIN_ID")
    ros_domain_id = int(env_domain) if env_domain else _allocate_domain_id(run_id)
    registry = ProcessRegistry(registry_path(run_id, runs_root))

    try:
        scenario = read_yaml_or_json(scenario_path)
        validate_scenario(scenario)
        _append_check(checks, "schema_validation", "pass")
        enforce_execution_guard(scenario)
        _append_check(checks, "execution_guard", "pass")
        infra_image_digest = _resolve_infra_image_digest(scenario["launch"].get("entrypoint"))

        if args.dry_run:
            # A dry run never launches anything, so it must never be
            # confused with a real, executed, passing release check: the
            # schema enforces this by requiring a `process_execution`
            # check, and rejecting `result: pass` unless that check is
            # `executed`.
            _append_check(
                checks, "process_execution", "not_run", "dry-run: process not launched"
            )
            result = "not_run"
        else:
            plan = build_launch_plan(scenario)
            compose_file = (
                scenario["launch"].get("file") if plan.entrypoint == "docker_compose" else None
            )
            coordinator = SignalCoordinator()
            runner = ProcessGroupRunner(coordinator)
            log_path = run_dir / "process.log"
            runner.start(
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
                        "entrypoint": plan.entrypoint,
                        "compose_file": compose_file,
                        "compose_env": _compose_env_snapshot(),
                        "state": "running",
                    }
                )

            # Graph readiness must be observed while the launched process is
            # still alive. Observing after `wait()` would only ever see a
            # process that has already exited (and, for `docker compose run
            # --rm`, a container that no longer exists), which is exactly the
            # "fake pass" failure mode this harness must not reproduce.
            graph_check_embedded = os.environ.get("ROBOTICS_GRAPH_CHECK_EMBEDDED") == "1"
            skip_observer = os.environ.get("ROBOTICS_SKIP_ROS_OBSERVER") == "1"
            live_observation: tuple[str, str] | None = None
            if not graph_check_embedded and not skip_observer:
                try:
                    observation = observe_ros_graph(
                        scenario["expected_ros_graph"],
                        wall_timeout_sec=int(
                            scenario["expected_ros_graph"]["graph_ready_timeout_sec"]
                        ),
                    )
                    live_observation = (
                        "pass" if observation.ok else "fail",
                        observation.message,
                    )
                except RosObserverError as exc:
                    live_observation = ("fail", str(exc))

            process = runner.wait()
            if runner.process is not None:
                entry = registry.read() or {}
                entry.update(
                    {
                        "run_id": run_id,
                        "pid": runner.process.pid,
                        "scenario_id": scenario["scenario_id"],
                        "command": plan.command,
                        "entrypoint": plan.entrypoint,
                        "compose_file": compose_file,
                        "state": "exited",
                        "returncode": process.returncode,
                    }
                )
                registry.write(entry)
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
                if graph_check_embedded:
                    # The launch plan itself runs a sibling container (for
                    # example: `docker compose up --exit-code-from
                    # ros-observer`) that performs a live rclpy check on the
                    # same network and writes its verdict to a result file.
                    # `process_exit == 0` on its own is not proof the graph
                    # was actually ready -- e.g. a race where the sibling
                    # never ran -- so this reads that file from disk and only
                    # passes when it explicitly says `ok: true`, recording
                    # its sha256 in evidence for auditability.
                    outcome, message = _check_embedded_graph_result(extra_artifacts)
                    _append_check(checks, "graph_ready", outcome, message)
                    result = outcome
                elif skip_observer:
                    # A skipped check must never be reported as a passing
                    # release/cross-repo check. Fail closed instead of lying.
                    _append_check(
                        checks, "graph_ready", "skip", "observer skipped by env; fail-closed"
                    )
                    result = "fail"
                elif live_observation is not None:
                    outcome, message = live_observation
                    _append_check(checks, "graph_ready", outcome, message)
                    result = outcome
                else:
                    _append_check(checks, "graph_ready", "fail", "graph observation did not run")
                    result = "fail"
    except (SchemaValidationError, ExecutionGuardError, LaunchError, MissingDigestError) as exc:
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
            infra_image_digest=infra_image_digest,
            signed=False,
            business_repo=_resolve_business_repo(args),
            extra_artifacts=extra_artifacts or None,
        )
        try:
            validate_evidence(evidence)
        except SchemaValidationError as exc:
            console.print(f"evidence schema warning: {exc}")
        write_json(evidence_path, evidence)
        console.print(f"evidence: {evidence_path}")
        if result not in ("pass", "not_run") or args.dry_run:
            registry.clear()

    return 0 if result in ("pass", "not_run") else 2


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
    run.add_argument(
        "--business-repo-url",
        default="",
        help="Repo URL this run is testing on behalf of (else falls back to GITHUB_* env)",
    )
    run.add_argument(
        "--business-repo-commit",
        default="",
        help="Commit SHA for --business-repo-url (else falls back to GITHUB_SHA)",
    )
    run.add_argument(
        "--business-repo-dirty",
        action="store_true",
        help="Mark the business repo working tree as dirty in evidence",
    )
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

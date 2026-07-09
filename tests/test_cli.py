from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from robotics_simulation_harness.cli import main

ROOT = Path(__file__).resolve().parents[1]


def _resolve_generic_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    resolved = tmp_path / "resolved.json"
    trace = tmp_path / "trace.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "robotics-harness",
            "scenario",
            "resolve",
            "--composition",
            str(ROOT / "examples" / "generic" / "composition.yaml"),
            "--output",
            str(resolved),
            "--trace",
            str(trace),
        ],
    )
    assert main() == 0
    assert resolved.exists()
    assert trace.exists()
    return resolved


def test_cli_real_run_without_ros_graph_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real process that never publishes the required ROS graph must not
    be reported as an overall `pass`, even though it executed successfully.
    This is the regression test for the harness `run` fake-pass finding:
    `process_execution` alone must never imply `graph_ready`.
    """
    evidence = tmp_path / "evidence.json"
    runs_root = tmp_path / "runs"
    monkeypatch.setenv("ROBOTICS_RUNS_ROOT", str(runs_root))

    resolved = _resolve_generic_scenario(tmp_path, monkeypatch)
    data = json.loads(resolved.read_text(encoding="utf-8"))
    data["launch"] = {
        "entrypoint": "external_command",
        "package": sys.executable,
        "arguments": ["-c", "print('ok')"],
    }
    resolved.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "robotics-harness",
            "run",
            "--scenario",
            str(resolved),
            "--evidence",
            str(evidence),
            "--run-id",
            "test-run",
        ],
    )
    assert main() == 2
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_data["result"] == "fail"
    assert any(
        check["name"] == "process_execution" and check["result"] == "executed"
        for check in evidence_data["checks"]
    )
    assert any(
        check["name"] == "graph_ready" and check["result"] == "fail"
        for check in evidence_data["checks"]
    )


def test_cli_skip_observer_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = tmp_path / "evidence.json"
    runs_root = tmp_path / "runs"
    monkeypatch.setenv("ROBOTICS_RUNS_ROOT", str(runs_root))
    monkeypatch.setenv("ROBOTICS_SKIP_ROS_OBSERVER", "1")

    resolved = _resolve_generic_scenario(tmp_path, monkeypatch)
    data = json.loads(resolved.read_text(encoding="utf-8"))
    data["launch"] = {
        "entrypoint": "external_command",
        "package": sys.executable,
        "arguments": ["-c", "print('ok')"],
    }
    resolved.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "robotics-harness",
            "run",
            "--scenario",
            str(resolved),
            "--evidence",
            str(evidence),
            "--run-id",
            "test-run-skip",
        ],
    )
    assert main() == 2
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_data["result"] == "fail"
    assert any(
        check["name"] == "graph_ready" and check["result"] == "skip"
        for check in evidence_data["checks"]
    )


def test_cli_graph_check_embedded_trusts_process_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = tmp_path / "evidence.json"
    runs_root = tmp_path / "runs"
    monkeypatch.setenv("ROBOTICS_RUNS_ROOT", str(runs_root))
    monkeypatch.setenv("ROBOTICS_GRAPH_CHECK_EMBEDDED", "1")

    resolved = _resolve_generic_scenario(tmp_path, monkeypatch)
    data = json.loads(resolved.read_text(encoding="utf-8"))
    data["launch"] = {
        "entrypoint": "external_command",
        "package": sys.executable,
        "arguments": ["-c", "print('ok')"],
    }
    resolved.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "robotics-harness",
            "run",
            "--scenario",
            str(resolved),
            "--evidence",
            str(evidence),
            "--run-id",
            "test-run-embedded",
        ],
    )
    assert main() == 0
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_data["result"] == "pass"
    assert any(
        check["name"] == "graph_ready" and check["result"] == "pass"
        for check in evidence_data["checks"]
    )


def test_cli_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = tmp_path / "resolved.json"
    evidence = tmp_path / "validation.json"
    monkeypatch.setenv("ROBOTICS_RUNS_ROOT", str(tmp_path / "runs"))

    composition = ROOT / "examples" / "generic" / "composition.yaml"
    monkeypatch.setattr(
        "sys.argv",
        [
            "robotics-harness",
            "scenario",
            "resolve",
            "--composition",
            str(composition),
            "--output",
            str(resolved),
            "--trace",
            str(tmp_path / "trace.json"),
        ],
    )
    assert main() == 0

    monkeypatch.setattr(
        "sys.argv",
        [
            "robotics-harness",
            "run",
            "--scenario",
            str(resolved),
            "--evidence",
            str(evidence),
            "--run-id",
            "dry-run",
            "--dry-run",
        ],
    )
    assert main() == 0
    data = json.loads(evidence.read_text(encoding="utf-8"))
    assert data["result"] == "pass"
    assert any(check["name"] == "dry_run" for check in data["checks"])
    assert not any(
        check["name"] == "process_execution" and check["result"] == "executed"
        for check in data["checks"]
    )

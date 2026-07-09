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


def _run_embedded_graph_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, run_id: str
) -> Path:
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
            run_id,
        ],
    )
    main()
    return evidence


def test_cli_graph_check_embedded_reads_observed_file_and_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_path = tmp_path / "graph-observed.json"
    observed_path.write_text(
        json.dumps({"ok": True, "message": "graph ready", "observed": {}}), encoding="utf-8"
    )
    monkeypatch.setenv("ROBOTICS_GRAPH_OBSERVED_PATH", str(observed_path))

    evidence = _run_embedded_graph_check(tmp_path, monkeypatch, run_id="test-run-embedded-pass")
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_data["result"] == "pass"
    assert any(
        check["name"] == "graph_ready" and check["result"] == "pass"
        for check in evidence_data["checks"]
    )
    assert any(artifact["name"] == "graph-observed" for artifact in evidence_data["artifacts"])


def test_cli_graph_check_embedded_fails_when_observer_reports_not_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_path = tmp_path / "graph-observed.json"
    observed_path.write_text(
        json.dumps({"ok": False, "message": "topic readiness failed for /clock"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ROBOTICS_GRAPH_OBSERVED_PATH", str(observed_path))

    evidence = _run_embedded_graph_check(tmp_path, monkeypatch, run_id="test-run-embedded-fail")
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_data["result"] == "fail"
    assert any(
        check["name"] == "graph_ready"
        and check["result"] == "fail"
        and "topic readiness failed" in check.get("message", "")
        for check in evidence_data["checks"]
    )


def test_cli_graph_check_embedded_fails_closed_when_result_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROBOTICS_GRAPH_OBSERVED_PATH", str(tmp_path / "does-not-exist.json"))

    evidence = _run_embedded_graph_check(tmp_path, monkeypatch, run_id="test-run-embedded-missing")
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_data["result"] == "fail"
    assert any(
        check["name"] == "graph_ready" and check["result"] == "fail"
        for check in evidence_data["checks"]
    )


def test_cli_docker_compose_run_without_digest_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `docker_compose` run always launches a specific, real image.
    Without `ROBOTICS_INFRA_IMAGE_DIGEST` there is no truthful digest to
    record, so the harness must refuse to run rather than fabricate one.
    """
    evidence = tmp_path / "evidence.json"
    runs_root = tmp_path / "runs"
    monkeypatch.setenv("ROBOTICS_RUNS_ROOT", str(runs_root))
    monkeypatch.delenv("ROBOTICS_INFRA_IMAGE_DIGEST", raising=False)

    resolved = _resolve_generic_scenario(tmp_path, monkeypatch)
    data = json.loads(resolved.read_text(encoding="utf-8"))
    data["launch"] = {
        "entrypoint": "docker_compose",
        "package": "docker",
        "file": "compose.yaml",
        "arguments": ["run", "--rm", "simulation"],
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
            "test-run-missing-digest",
        ],
    )
    assert main() == 2
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_data["result"] == "fail"
    assert evidence_data["infra_image_digest"] == "sha256:" + "0" * 64
    assert any(
        check["name"] == "preflight" and "ROBOTICS_INFRA_IMAGE_DIGEST" in check.get("message", "")
        for check in evidence_data["checks"]
    )


def test_cli_business_repo_populated_from_github_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = tmp_path / "evidence.json"
    runs_root = tmp_path / "runs"
    monkeypatch.setenv("ROBOTICS_RUNS_ROOT", str(runs_root))
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "mmkolpakov/droning-simulation-infra")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)

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
            "test-run-business-repo",
            "--dry-run",
        ],
    )
    assert main() == 0
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_data["business_repo"] == {
        "url": "https://github.com/mmkolpakov/droning-simulation-infra",
        "commit": "a" * 40,
        "dirty": False,
    }


def test_cli_business_repo_explicit_flags_override_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = tmp_path / "evidence.json"
    runs_root = tmp_path / "runs"
    monkeypatch.setenv("ROBOTICS_RUNS_ROOT", str(runs_root))
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "mmkolpakov/should-not-be-used")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)

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
            "test-run-business-repo-explicit",
            "--dry-run",
            "--business-repo-url",
            "https://github.com/explicit/repo",
            "--business-repo-commit",
            "c" * 40,
            "--business-repo-dirty",
        ],
    )
    assert main() == 0
    evidence_data = json.loads(evidence.read_text(encoding="utf-8"))
    assert evidence_data["business_repo"] == {
        "url": "https://github.com/explicit/repo",
        "commit": "c" * 40,
        "dirty": True,
    }


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
    # A dry-run must never be schema-indistinguishable from a real passing
    # release check: it never launched anything, so `result` must be
    # `not_run`, not a fake `pass`.
    assert data["result"] == "not_run"
    assert any(
        check["name"] == "process_execution" and check["result"] == "not_run"
        for check in data["checks"]
    )
    assert not any(
        check["name"] == "process_execution" and check["result"] == "executed"
        for check in data["checks"]
    )

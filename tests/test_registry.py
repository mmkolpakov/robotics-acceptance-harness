from __future__ import annotations

import os
import subprocess
from typing import Any

import pytest

from robotics_simulation_harness.registry import stop_registry_entry


def _already_exited(*_args: object, **_kwargs: object) -> None:
    raise ProcessLookupError("no such process")


def _spawn_sleeper() -> subprocess.Popen[str]:
    kwargs: dict[str, object] = {"text": True}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    command = ["sleep", "5"] if os.name == "posix" else ["ping", "-t", "5"]
    return subprocess.Popen(command, **kwargs)


@pytest.mark.skipif(os.name != "posix", reason="process-group stop semantics are posix-specific")
def test_stop_registry_entry_terminates_process_group() -> None:
    process = _spawn_sleeper()
    try:
        pgid = os.getpgid(process.pid)
        entry: dict[str, Any] = {"pid": process.pid, "pgid": pgid}
        stop_registry_entry(entry)
        process.wait(timeout=5)
        assert process.returncode is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_stop_registry_entry_runs_compose_down_for_docker_compose_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`docker compose run`/`up` containers are owned by the Docker daemon,
    not the local process group. `stop` must explicitly bring the compose
    stack down or a "stopped" run leaks containers/network/volumes that
    collide with the next run's allocation.
    """
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(os, "kill", _already_exited)
    if os.name == "posix":
        monkeypatch.setattr(os, "killpg", _already_exited)

    entry = {
        "pid": 999999,
        "pgid": 999999,
        "entrypoint": "docker_compose",
        "compose_file": "compose.yaml",
    }
    stop_registry_entry(entry)

    assert calls, "expected `docker compose down` to be invoked"
    assert calls[0][:3] == ["docker", "compose", "-f"]
    assert "down" in calls[0]


def test_stop_registry_entry_passes_stored_compose_env_to_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`down` must run with the same `COMPOSE_PROJECT_NAME`/`ROS_DOMAIN_ID`
    `start` used, or it tears down the wrong (default) compose project
    instead of this run's, leaking the real one.
    """
    captured_envs: list[dict[str, str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_envs.append(dict(kwargs.get("env") or {}))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(os, "kill", _already_exited)
    if os.name == "posix":
        monkeypatch.setattr(os, "killpg", _already_exited)

    entry = {
        "pid": 999999,
        "pgid": 999999,
        "entrypoint": "docker_compose",
        "compose_file": "compose.yaml",
        "compose_env": {
            "COMPOSE_PROJECT_NAME": "robotics-test-run-42",
            "ROS_DOMAIN_ID": "73",
        },
    }
    stop_registry_entry(entry)

    assert captured_envs, "expected `docker compose down` to be invoked with an env"
    assert captured_envs[0]["COMPOSE_PROJECT_NAME"] == "robotics-test-run-42"
    assert captured_envs[0]["ROS_DOMAIN_ID"] == "73"


def test_stop_registry_entry_skips_compose_down_for_non_compose_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda command, **_kw: calls.append(command))
    monkeypatch.setattr(os, "kill", _already_exited)
    if os.name == "posix":
        monkeypatch.setattr(os, "killpg", _already_exited)

    entry = {"pid": 999999, "pgid": 999999, "entrypoint": "external_command"}
    stop_registry_entry(entry)

    assert not calls

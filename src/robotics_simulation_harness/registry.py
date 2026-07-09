from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any


class ProcessRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def registry_path(run_id: str, runs_root: Path) -> Path:
    return runs_root / run_id / "process-registry.json"


def stop_registry_entry(entry: dict[str, Any]) -> None:
    pid = int(entry["pid"])
    pgid = int(entry.get("pgid") or pid)
    if os.name == "posix":
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        else:
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    os.killpg(pgid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(pgid, signal.SIGKILL)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
    _stop_compose_stack(entry)


def _stop_compose_stack(entry: dict[str, Any]) -> None:
    # `docker compose run`/`up` launch containers managed by the Docker
    # daemon, not by the local process group: killing the local `docker
    # compose` CLI (above) can leave containers, the compose network, and
    # anonymous volumes running. `stop` must bring the stack down explicitly
    # or a "stopped" run leaks resources that collide with the next run's
    # ROS_DOMAIN_ID/network allocation.
    #
    # Compose resolves the project to tear down from `COMPOSE_PROJECT_NAME`
    # (falling back to the compose file's directory name), and this
    # project's compose files interpolate a required `ROS_DOMAIN_ID` env var
    # into every service. Running `down` without the exact env `start` used
    # either targets the *wrong* (default) project -- leaving this run's
    # containers/network/volumes running -- or fails outright because
    # `ROS_DOMAIN_ID` is unset. The entry must therefore carry whatever env
    # `start` captured so `stop` can reproduce it.
    if entry.get("entrypoint") != "docker_compose":
        return
    compose_file = entry.get("compose_file")
    if not compose_file:
        return
    env = dict(os.environ)
    for key, value in (entry.get("compose_env") or {}).items():
        if value is not None:
            env[str(key)] = str(value)
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "down", "--remove-orphans", "-t", "10"],
            check=False,
            timeout=30,
            env=env,
        )

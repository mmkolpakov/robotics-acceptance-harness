from __future__ import annotations

import json
import os
import signal
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
            return
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:
        os.kill(pid, signal.SIGTERM)

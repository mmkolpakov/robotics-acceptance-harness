from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcessResult:
    returncode: int


class ProcessGroupRunner:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None

    def run(self, command: Sequence[str], cwd: Path | None = None) -> ProcessResult:
        kwargs: dict[str, object] = {
            "cwd": cwd,
            "text": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        elif os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        self.process = subprocess.Popen(command, **kwargs)
        self._install_signal_handlers()
        assert self.process.stdout is not None
        for line in self.process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
        return ProcessResult(self.process.wait())

    def terminate_tree(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        if os.name == "posix":
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
        elif os.name == "nt":
            self.process.send_signal(signal.CTRL_BREAK_EVENT)

    def _install_signal_handlers(self) -> None:
        def handler(signum: int, _frame: object) -> None:
            self.terminate_tree()
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

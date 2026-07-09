from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .signal_coordinator import SignalCoordinator


@dataclass
class ProcessResult:
    returncode: int
    timed_out: bool = False
    stopped_by_signal: bool = False


class ProcessGroupRunner:
    def __init__(self, coordinator: SignalCoordinator | None = None) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.coordinator = coordinator or SignalCoordinator()
        self.log_path: Path | None = None

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        wall_timeout_sec: int,
        log_path: Path | None = None,
    ) -> ProcessResult:
        self.log_path = log_path
        kwargs: dict[str, object] = {
            "cwd": cwd,
            "text": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "bufsize": 1,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        elif os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        self.process = subprocess.Popen(list(command), **kwargs)
        assert self.process.stdout is not None
        self.coordinator.register(self.terminate_tree)
        self.coordinator.install()

        lines: queue.Queue[str | None] = queue.Queue()

        def reader() -> None:
            assert self.process is not None
            assert self.process.stdout is not None
            for line in self.process.stdout:
                lines.put(line)
            lines.put(None)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        started = time.monotonic()
        timed_out = False
        stopped_by_signal = False
        log_handle = log_path.open("w", encoding="utf-8") if log_path else None
        try:
            while True:
                if self.coordinator.stopped:
                    stopped_by_signal = True
                    self.terminate_tree()
                    break
                if time.monotonic() - started >= wall_timeout_sec:
                    timed_out = True
                    self.terminate_tree()
                    break
                try:
                    item = lines.get(timeout=0.2)
                except queue.Empty:
                    if self.process.poll() is not None and lines.empty():
                        break
                    continue
                if item is None:
                    break
                if log_handle is not None:
                    log_handle.write(item)
                    log_handle.flush()
            returncode = self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.terminate_tree()
            returncode = self.process.wait()
            timed_out = True
        finally:
            if log_handle is not None:
                log_handle.close()
            thread.join(timeout=1)

        return ProcessResult(
            returncode=returncode,
            timed_out=timed_out,
            stopped_by_signal=stopped_by_signal,
        )

    def terminate_tree(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        if os.name == "posix":
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
        elif os.name == "nt":
            self.process.send_signal(signal.CTRL_BREAK_EVENT)

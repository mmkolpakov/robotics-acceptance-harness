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
from typing import TextIO

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
        self._lines: queue.Queue[str | None] | None = None
        self._reader: threading.Thread | None = None
        self._log_handle: TextIO | None = None
        self._started: float | None = None
        self._wall_timeout_sec: int = 0

    def start(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        wall_timeout_sec: int,
        log_path: Path | None = None,
    ) -> subprocess.Popen[str]:
        self.log_path = log_path
        self._wall_timeout_sec = wall_timeout_sec
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

        self._lines = queue.Queue()

        def reader() -> None:
            assert self.process is not None
            assert self.process.stdout is not None
            assert self._lines is not None
            for line in self.process.stdout:
                self._lines.put(line)
            self._lines.put(None)

        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()
        self._started = time.monotonic()
        self._log_handle = log_path.open("w", encoding="utf-8") if log_path else None
        return self.process

    def wait(self) -> ProcessResult:
        if self.process is None or self._lines is None or self._started is None:
            raise RuntimeError("process was not started")

        timed_out = False
        stopped_by_signal = False
        log_handle = self._log_handle
        try:
            while True:
                if self.coordinator.stopped:
                    stopped_by_signal = True
                    self.terminate_tree()
                    break
                if time.monotonic() - self._started >= self._wall_timeout_sec:
                    timed_out = True
                    self.terminate_tree()
                    break
                try:
                    item = self._lines.get(timeout=0.2)
                except queue.Empty:
                    if self.process.poll() is not None and self._lines.empty():
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
            if self._reader is not None:
                self._reader.join(timeout=1)

        return ProcessResult(
            returncode=returncode,
            timed_out=timed_out,
            stopped_by_signal=stopped_by_signal,
        )

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        wall_timeout_sec: int,
        log_path: Path | None = None,
    ) -> ProcessResult:
        self.start(
            command,
            cwd=cwd,
            wall_timeout_sec=wall_timeout_sec,
            log_path=log_path,
        )
        return self.wait()

    def terminate_tree(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        if os.name == "posix":
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
        elif os.name == "nt":
            self.process.send_signal(signal.CTRL_BREAK_EVENT)

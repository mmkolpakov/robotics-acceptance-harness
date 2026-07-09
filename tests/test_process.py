from __future__ import annotations

import os
import sys
import time

import pytest

from robotics_simulation_harness.process import (
    _LOG_QUEUE_MAXSIZE,
    ProcessGroupRunner,
)
from robotics_simulation_harness.signal_coordinator import SignalCoordinator


def test_log_queue_is_bounded() -> None:
    # A flooding child process must not be able to grow the in-memory line
    # buffer without limit: that is memory-growth-until-OOM, not a bounded
    # wall-timeout failure.
    assert _LOG_QUEUE_MAXSIZE > 0
    assert _LOG_QUEUE_MAXSIZE < 1_000_000


@pytest.mark.skipif(os.name != "posix", reason="signal-ignoring child needs posix semantics")
def test_wait_escalates_to_sigkill_when_process_ignores_sigterm() -> None:
    """A process that ignores SIGTERM must still be reaped in bounded time:
    `wait()` has to escalate to SIGKILL instead of blocking forever on
    `Popen.wait()`.
    """
    script = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(60)\n"
    )
    runner = ProcessGroupRunner(SignalCoordinator())
    # Escalate almost immediately so the test doesn't need to wait out the
    # real production grace periods.
    from robotics_simulation_harness import process as process_module

    original_grace = process_module._SIGTERM_GRACE_SEC
    process_module._SIGTERM_GRACE_SEC = 1
    try:
        runner.start(
            [sys.executable, "-c", script],
            wall_timeout_sec=1,
        )
        started = time.monotonic()
        result = runner.wait()
        elapsed = time.monotonic() - started
    finally:
        process_module._SIGTERM_GRACE_SEC = original_grace

    assert result.timed_out
    # SIGTERM alone would never end this process (it is ignored); bounded
    # completion here proves SIGKILL escalation actually happened.
    assert elapsed < 30
    assert result.returncode != 0


def test_terminate_tree_force_uses_sigkill(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []

    class _FakeProcess:
        pid = 4242

        def poll(self) -> int | None:
            return None

    runner = ProcessGroupRunner(SignalCoordinator())
    runner.process = _FakeProcess()  # type: ignore[assignment]

    monkeypatch.setattr(os, "getpgid", lambda _pid: 4242)

    def fake_killpg(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))

    monkeypatch.setattr(os, "killpg", fake_killpg)

    runner.terminate_tree(force=True)

    import signal

    assert calls == [(4242, signal.SIGKILL)]

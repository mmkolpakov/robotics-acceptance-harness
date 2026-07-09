from __future__ import annotations

import signal
import threading
from collections.abc import Callable


class SignalCoordinator:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._callbacks: list[Callable[[], None]] = []
        self._installed = False

    def register(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    def install(self) -> None:
        if self._installed:
            return

        def handler(_signum: int, _frame: object) -> None:
            self._stop.set()
            for callback in list(self._callbacks):
                callback()

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)
        self._installed = True

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

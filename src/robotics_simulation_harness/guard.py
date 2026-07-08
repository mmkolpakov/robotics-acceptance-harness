from __future__ import annotations

import os
from typing import Any


class ExecutionGuardError(RuntimeError):
    pass


def enforce_execution_guard(scenario: dict[str, Any]) -> None:
    target = scenario.get("target_environment")
    guard = scenario.get("safety", {}).get("execution_guard", {})
    allow_physical = bool(guard.get("allow_physical_actuation"))

    if target == "simulation":
        if allow_physical:
            raise ExecutionGuardError("simulation scenarios must not allow physical actuation")
        return

    confirmation_env = guard.get("required_confirmation_env")
    if target in {"hil", "real_robot"}:
        if not confirmation_env:
            raise ExecutionGuardError("hil and real_robot scenarios require confirmation env")
        if os.getenv(confirmation_env) != "I_ACCEPT_PHYSICAL_RISK":
            raise ExecutionGuardError(f"missing explicit confirmation in {confirmation_env}")

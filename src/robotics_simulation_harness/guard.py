from __future__ import annotations

from typing import Any


class ExecutionGuardError(RuntimeError):
    pass


def enforce_execution_guard(scenario: dict[str, Any]) -> None:
    target = scenario.get("target_environment")
    guard = scenario.get("safety", {}).get("execution_guard", {})
    allow_physical = bool(guard.get("allow_physical_actuation"))

    if target != "simulation":
        raise ExecutionGuardError(
            "foundation harness executes only simulation scenarios; "
            f"rejected target_environment={target}"
        )
    if allow_physical:
        raise ExecutionGuardError("simulation scenarios must not allow physical actuation")

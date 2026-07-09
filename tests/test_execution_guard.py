from __future__ import annotations

import pytest

from robotics_simulation_harness.guard import ExecutionGuardError, enforce_execution_guard


def test_simulation_guard_rejects_physical_actuation() -> None:
    scenario = {
        "target_environment": "simulation",
        "safety": {
            "execution_guard": {
                "allow_physical_actuation": True,
            }
        },
    }

    with pytest.raises(ExecutionGuardError):
        enforce_execution_guard(scenario)


def test_hil_is_rejected_in_foundation() -> None:
    scenario = {
        "target_environment": "hil",
        "safety": {
            "execution_guard": {
                "allow_physical_actuation": True,
                "required_confirmation_env": "ROBOTICS_CONFIRM_HIL",
            }
        },
    }

    with pytest.raises(ExecutionGuardError):
        enforce_execution_guard(scenario)

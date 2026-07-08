from __future__ import annotations

import os

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


def test_hil_guard_requires_explicit_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = {
        "target_environment": "hil",
        "safety": {
            "execution_guard": {
                "allow_physical_actuation": True,
                "required_confirmation_env": "ROBOTICS_CONFIRM_HIL",
            }
        },
    }

    monkeypatch.delenv("ROBOTICS_CONFIRM_HIL", raising=False)
    with pytest.raises(ExecutionGuardError):
        enforce_execution_guard(scenario)

    monkeypatch.setenv("ROBOTICS_CONFIRM_HIL", "I_ACCEPT_PHYSICAL_RISK")
    enforce_execution_guard(scenario)
    assert os.getenv("ROBOTICS_CONFIRM_HIL") == "I_ACCEPT_PHYSICAL_RISK"

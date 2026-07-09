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


def test_default_scenario_is_safe_simulation() -> None:
    scenario = {
        "target_environment": "simulation",
        "safety": {"execution_guard": {"allow_physical_actuation": False}},
    }
    enforce_execution_guard(scenario)


def test_autouse_guard_fails_closed_by_default(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def robotics_scenario():
            return {
                "target_environment": "hardware",
                "safety": {"execution_guard": {"allow_physical_actuation": True}},
            }

        def test_needs_hardware(robotics_scenario):
            assert robotics_scenario["target_environment"] == "hardware"
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)


def test_autouse_guard_allows_marked_and_flagged_test(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def robotics_scenario():
            return {
                "target_environment": "hardware",
                "safety": {"execution_guard": {"allow_physical_actuation": True}},
            }

        @pytest.mark.robotics_physical_actuation
        def test_needs_hardware(robotics_scenario):
            assert robotics_scenario["target_environment"] == "hardware"
        """
    )
    result = pytester.runpytest("--robotics-allow-physical-actuation")
    result.assert_outcomes(passed=1)


def test_autouse_guard_rejects_flag_without_marker(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def robotics_scenario():
            return {
                "target_environment": "hardware",
                "safety": {"execution_guard": {"allow_physical_actuation": True}},
            }

        def test_needs_hardware(robotics_scenario):
            assert robotics_scenario["target_environment"] == "hardware"
        """
    )
    result = pytester.runpytest("--robotics-allow-physical-actuation")
    result.assert_outcomes(errors=1)

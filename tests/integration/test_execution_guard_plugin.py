"""Integration tests: exercise the plugin as pytest itself would load it,
via a nested `pytest` run (`pytester`). Slower than the unit tests in
`tests/unit/`; run separately with `make test-integration`.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


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

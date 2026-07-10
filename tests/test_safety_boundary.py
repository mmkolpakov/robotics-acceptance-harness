from __future__ import annotations

from pathlib import Path

import pytest

from robotics_simulation_harness.plugin import _load_scenario

FIXTURES = Path(__file__).parent / "fixtures"


def test_loader_accepts_only_simulation() -> None:
    scenario = _load_scenario(FIXTURES / "simulation.yaml")
    assert scenario["target_environment"] == "simulation"


@pytest.mark.parametrize("fixture_name", ["hil.yaml", "real-robot.yaml"])
def test_loader_rejects_physical_environments(fixture_name: str) -> None:
    with pytest.raises(pytest.UsageError, match="accepts only"):
        _load_scenario(FIXTURES / fixture_name)

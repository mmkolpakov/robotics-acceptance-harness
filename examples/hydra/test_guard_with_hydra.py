"""Example: consuming repositories compose their scenario config with Hydra
and hand the resolved mapping to this plugin's `robotics_scenario` fixture.

Run from this directory with:
    python -m pytest examples/hydra/test_guard_with_hydra.py -p robotics_simulation_harness.guard
"""

from __future__ import annotations

from typing import Any

import pytest
from hydra import compose, initialize
from omegaconf import OmegaConf


def _compose_scenario(*overrides: str) -> dict[str, Any]:
    with initialize(version_base=None, config_path="conf"):
        cfg = compose(config_name="config", overrides=list(overrides))
    return OmegaConf.to_container(cfg, resolve=True)["scenario"]


@pytest.fixture
def robotics_scenario() -> dict[str, Any]:
    return _compose_scenario()


def test_hydra_composed_simulation_scenario_passes_guard(robotics_scenario: dict[str, Any]) -> None:
    assert robotics_scenario["target_environment"] == "simulation"


@pytest.mark.robotics_physical_actuation
class TestHardwareOptIn:
    """Run with `--robotics-allow-physical-actuation`; without it, the
    autouse execution guard fails this test closed before it even starts."""

    @pytest.fixture
    def robotics_scenario(self) -> dict[str, Any]:
        return _compose_scenario("scenario=hardware")

    def test_hydra_composed_hardware_scenario(self, robotics_scenario: dict[str, Any]) -> None:
        assert robotics_scenario["target_environment"] == "hardware"

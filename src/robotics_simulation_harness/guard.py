"""Execution guard: the one piece of the old harness that is genuine
business/safety logic rather than DevOps orchestration self-rolled.

Everything else the harness used to do (scenario resolution, process
supervision, ROS graph polling, evidence writing) is now the job of
`Hydra`, `pytest-docker`, `launch_testing_ros`, and `pytest --junitxml` +
`slsa-github-generator` respectively. This module survives as a `pytest`
plugin: an autouse fixture that fails a test closed against physical
actuation unless it explicitly opts in.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest


class ExecutionGuardError(RuntimeError):
    """Raised when a scenario violates the simulation-only execution guard."""


def enforce_execution_guard(scenario: Mapping[str, Any]) -> None:
    """Fail closed unless `scenario` is an explicit, non-actuating simulation.

    `scenario` is any mapping with `target_environment` and
    `safety.execution_guard.allow_physical_actuation` keys. In practice this
    is a Hydra-composed config passed through
    `OmegaConf.to_container(cfg, resolve=True)`, but it is a plain
    `Mapping` so callers are never forced to depend on OmegaConf.
    """
    target = scenario.get("target_environment")
    guard = scenario.get("safety", {}).get("execution_guard", {})
    allow_physical = bool(guard.get("allow_physical_actuation"))

    if target != "simulation":
        raise ExecutionGuardError(
            "robotics-simulation-harness executes only simulation scenarios; "
            f"rejected target_environment={target!r}"
        )
    if allow_physical:
        raise ExecutionGuardError("simulation scenarios must not allow physical actuation")


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("robotics-execution-guard")
    group.addoption(
        "--robotics-allow-physical-actuation",
        action="store_true",
        default=False,
        help=(
            "Explicit, operator-supplied acknowledgement that this pytest "
            "invocation may command real hardware. Only lifts the guard for "
            "tests also carrying the `robotics_physical_actuation` marker; "
            "refusing physical actuation by default is the point of this "
            "guard."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "robotics_physical_actuation: this test intentionally targets "
        "physical hardware. Requires --robotics-allow-physical-actuation, "
        "or the autouse execution-guard fixture fails it closed.",
    )


@pytest.fixture
def robotics_scenario() -> dict[str, Any]:
    """The scenario under test, as a plain mapping.

    Override this fixture (typically from a Hydra-composed config) to
    describe a non-default target. Tests that need physical actuation must
    also carry the `robotics_physical_actuation` marker and the suite must
    be run with `--robotics-allow-physical-actuation`, or the autouse
    `robotics_execution_guard` fixture below fails them closed.
    """
    return {
        "target_environment": "simulation",
        "safety": {"execution_guard": {"allow_physical_actuation": False}},
    }


@pytest.fixture(autouse=True)
def robotics_execution_guard(request: pytest.FixtureRequest) -> None:
    """Autouse safety net enforced on every test in the suite.

    Hard-fails any test whose `robotics_scenario` violates the
    simulation-only execution guard, unless the test is marked
    `robotics_physical_actuation` *and* the run was launched with
    `--robotics-allow-physical-actuation`. Both are required so physical
    actuation is never enabled by a stray CLI flag alone (no marker) nor by
    a forgotten marker alone (no flag).
    """
    scenario = request.getfixturevalue("robotics_scenario")
    marker = request.node.get_closest_marker("robotics_physical_actuation")
    try:
        enforce_execution_guard(scenario)
    except ExecutionGuardError:
        if marker is not None and request.config.getoption(
            "--robotics-allow-physical-actuation"
        ):
            return
        raise

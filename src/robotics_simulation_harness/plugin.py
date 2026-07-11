"""Compatibility import for the renamed pytest plugin."""

from robotics_acceptance_harness.plugin import (
    _load_scenario,
    pytest_addoption,
    pytest_configure,
    robotics_scenario,
)

__all__ = [
    "_load_scenario",
    "pytest_addoption",
    "pytest_configure",
    "robotics_scenario",
]

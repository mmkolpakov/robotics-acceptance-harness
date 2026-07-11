"""Pytest plugin for validated acceptance scenarios."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from robotics_acceptance_harness.documents import (
    BundleValidationError,
    DocumentBundle,
    load_bundle,
)

_BUNDLE_KEY = pytest.StashKey[DocumentBundle]()


def _target_environment(bundle: DocumentBundle) -> str:
    scenario = bundle.scenario.data
    if bundle.scenario.schema_version == "acceptance-scenario.v1":
        return str(scenario["target_environment"])
    return str(scenario["execution"]["target_environment"])


def _guard_target(bundle: DocumentBundle) -> None:
    target = _target_environment(bundle)
    if target != "simulation":
        raise pytest.UsageError(
            "robotics-acceptance-harness accepts only target_environment=simulation in v0.5; "
            f"rejected target_environment={target}"
        )


def _load_scenario(path: Path) -> Any:
    try:
        bundle = load_bundle(path)
    except BundleValidationError as error:
        raise pytest.UsageError(f"invalid robotics scenario {path}: {error}") from error
    _guard_target(bundle)
    return bundle.scenario.data


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("robotics-acceptance-harness")
    group.addoption(
        "--robotics-scenario",
        dest="robotics_scenario_path",
        metavar="PATH",
        default=None,
        help="Path to a resolved acceptance-scenario YAML file.",
    )
    group.addoption(
        "--robotics-runtime",
        dest="robotics_runtime_path",
        metavar="PATH",
        default=None,
        help="Path to a runtime-manifest file required by acceptance-scenario.v2.",
    )
    group.addoption(
        "--robotics-model",
        dest="robotics_model_path",
        metavar="PATH",
        default=None,
        help="Path to the model-artifact-manifest declared by the scenario.",
    )
    group.addoption(
        "--robotics-dataset",
        dest="robotics_dataset_path",
        metavar="PATH",
        default=None,
        help="Path to the dataset-manifest declared by a playback scenario.",
    )
    group.addoption(
        "--robotics-permit",
        dest="robotics_permit_path",
        metavar="PATH",
        default=None,
        help="Path to an execution-permit for a physical target.",
    )


def pytest_configure(config: pytest.Config) -> None:
    scenario_path = config.getoption("robotics_scenario_path")
    if scenario_path is None:
        if config.getoption("help", default=False):
            return
        raise pytest.UsageError("--robotics-scenario PATH is required")

    path = Path(scenario_path).expanduser().resolve()
    try:
        bundle = load_bundle(
            path,
            runtime_path=config.getoption("robotics_runtime_path"),
            model_path=config.getoption("robotics_model_path"),
            dataset_path=config.getoption("robotics_dataset_path"),
            permit_path=config.getoption("robotics_permit_path"),
        )
    except BundleValidationError as error:
        if error.validation_message.startswith("cannot parse"):
            raise pytest.UsageError(
                f"cannot parse robotics scenario {path}: {error.validation_message}"
            ) from error
        raise pytest.UsageError(f"invalid robotics execution bundle: {error}") from error
    _guard_target(bundle)
    config.stash[_BUNDLE_KEY] = bundle


@pytest.fixture(scope="session")
def robotics_bundle(pytestconfig: pytest.Config) -> DocumentBundle:
    """Return the validated and cross-checked execution document bundle."""

    return pytestconfig.stash[_BUNDLE_KEY]


@pytest.fixture(scope="session")
def robotics_scenario(robotics_bundle: DocumentBundle) -> Any:
    """Return the validated scenario as a deeply immutable mapping."""

    return robotics_bundle.scenario.data

"""Pytest plugin for validated acceptance scenarios."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml
from robotics_runtime_contracts import ContractValidationError, validate_document

_SCENARIO_KEY = pytest.StashKey[Mapping[str, Any]]()


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _load_scenario(path: Path) -> Mapping[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise pytest.UsageError(f"cannot read robotics scenario {path}: {error}") from error
    except yaml.YAMLError as error:
        raise pytest.UsageError(f"cannot parse robotics scenario {path}: {error}") from error

    if not isinstance(payload, dict):
        raise pytest.UsageError(f"robotics scenario {path} must contain a YAML mapping")

    try:
        validate_document(payload)
    except (ContractValidationError, ValueError) as error:
        raise pytest.UsageError(f"invalid robotics scenario {path}: {error}") from error

    if payload["schema_version"] == "acceptance-scenario.v1":
        target = payload["target_environment"]
    else:
        target = payload["execution"]["target_environment"]
    if target != "simulation":
        raise pytest.UsageError(
            "robotics-acceptance-harness accepts only target_environment=simulation in v0.5; "
            f"rejected target_environment={target}"
        )

    return _freeze(payload)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("robotics-acceptance-harness")
    group.addoption(
        "--robotics-scenario",
        dest="robotics_scenario_path",
        metavar="PATH",
        default=None,
        help="Path to a resolved acceptance-scenario YAML file.",
    )


def pytest_configure(config: pytest.Config) -> None:
    scenario_path = config.getoption("robotics_scenario_path")
    if scenario_path is None:
        if config.getoption("help", default=False):
            return
        raise pytest.UsageError("--robotics-scenario PATH is required")

    path = Path(scenario_path).expanduser().resolve()
    config.stash[_SCENARIO_KEY] = _load_scenario(path)


@pytest.fixture(scope="session")
def robotics_scenario(pytestconfig: pytest.Config) -> Mapping[str, Any]:
    """Return the validated scenario as a deeply immutable mapping."""

    return pytestconfig.stash[_SCENARIO_KEY]

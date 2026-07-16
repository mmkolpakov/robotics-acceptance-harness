from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from robotics_acceptance_harness.documents import load_bundle
from robotics_acceptance_harness.plugin import _guard_target

FIXTURES = Path(__file__).parent / "fixtures"


def test_loader_accepts_only_simulation() -> None:
    bundle = load_bundle(
        FIXTURES / "simulation" / "scenario.yaml",
        runtime_path=FIXTURES / "simulation" / "runtime.yaml",
    )
    _guard_target(bundle)
    assert bundle.scenario.data["execution"]["target_environment"] == "simulation"


def test_loader_rejects_physical_environment() -> None:
    physical = FIXTURES / "physical"
    bundle = load_bundle(
        physical / "hil-scenario.yaml",
        runtime_path=physical / "hil-runtime.json",
        permit_path=physical / "hil-permit.json",
        verification_path=physical / "hil-verification.json",
        now=datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
    )
    with pytest.raises(pytest.UsageError, match="accepts only"):
        _guard_target(bundle)

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from robotics_runtime_contracts import migrate_scenario_v1_to_v2

from robotics_acceptance_harness.documents import BundleValidationError, load_bundle

FIXTURES = Path(__file__).parent / "fixtures" / "simulation"


def test_load_bundle_cross_checks_execution_documents() -> None:
    bundle = load_bundle(
        FIXTURES / "scenario.yaml",
        runtime_path=FIXTURES / "runtime.yaml",
    )

    assert bundle.scenario.schema_version == "acceptance-scenario.v1"
    assert bundle.runtime.schema_version == "runtime-manifest.v1"
    assert bundle.runtime.data["workload"]["kind"] == "none"


def test_load_bundle_rejects_runtime_mode_mismatch(tmp_path: Path) -> None:
    runtime = yaml.safe_load((FIXTURES / "runtime.yaml").read_text(encoding="utf-8"))
    runtime["execution"]["time_mode"] = "simulation_stepped"
    runtime_path = tmp_path / "runtime.yaml"
    runtime_path.write_text(yaml.safe_dump(runtime), encoding="utf-8")

    with pytest.raises(BundleValidationError) as caught:
        load_bundle(FIXTURES / "scenario.yaml", runtime_path=runtime_path)

    assert caught.value.json_path == "$.runtime.execution.time_mode"


def test_load_bundle_requires_runtime() -> None:
    with pytest.raises(BundleValidationError, match="requires a runtime manifest"):
        load_bundle(FIXTURES / "scenario.yaml")


def test_load_bundle_accepts_current_scenario_contract(tmp_path: Path) -> None:
    scenario = yaml.safe_load((FIXTURES / "scenario.yaml").read_text(encoding="utf-8"))
    current = migrate_scenario_v1_to_v2(
        scenario,
        metric_attributes={},
        time_authority_min_samples=30,
        max_clock_offset_p50_ms=1,
        max_clock_offset_p95_ms=2,
        max_clock_offset_ms=5,
    )
    current["schema_version"] = "acceptance-scenario.v4"
    policy = current["time_policy"]
    policy["max_time_authority_delivery_latency_p50_ms"] = policy.pop("max_clock_offset_p50_ms")
    policy["max_time_authority_delivery_latency_p95_ms"] = policy.pop("max_clock_offset_p95_ms")
    policy["max_time_authority_delivery_latency_ms"] = policy.pop("max_clock_offset_ms")
    scenario_path = tmp_path / "scenario-v4.yaml"
    scenario_path.write_text(yaml.safe_dump(current), encoding="utf-8")

    bundle = load_bundle(scenario_path, runtime_path=FIXTURES / "runtime.yaml")

    assert bundle.scenario.schema_version == "acceptance-scenario.v4"

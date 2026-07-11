from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from robotics_acceptance_harness.documents import BundleValidationError, load_bundle

FIXTURES = Path(__file__).parent / "fixtures" / "v2"


def test_load_bundle_cross_checks_v2_execution_documents() -> None:
    bundle = load_bundle(
        FIXTURES / "simulation.yaml",
        runtime_path=FIXTURES / "runtime.yaml",
    )

    assert bundle.scenario.schema_version == "acceptance-scenario.v2"
    assert bundle.runtime is not None
    assert bundle.runtime.schema_version == "runtime-manifest.v2"
    assert bundle.runtime.data["workload"]["kind"] == "none"


def test_load_bundle_rejects_runtime_mode_mismatch(tmp_path: Path) -> None:
    runtime = yaml.safe_load((FIXTURES / "runtime.yaml").read_text(encoding="utf-8"))
    runtime["execution"]["time_mode"] = "simulation_stepped"
    runtime_path = tmp_path / "runtime.yaml"
    runtime_path.write_text(yaml.safe_dump(runtime), encoding="utf-8")

    with pytest.raises(BundleValidationError) as caught:
        load_bundle(FIXTURES / "simulation.yaml", runtime_path=runtime_path)

    assert caught.value.json_path == "$.runtime.execution.time_mode"


def test_load_bundle_requires_runtime_for_v2() -> None:
    with pytest.raises(BundleValidationError, match="requires a runtime manifest"):
        load_bundle(FIXTURES / "simulation.yaml")


def test_v1_bundle_remains_self_contained() -> None:
    bundle = load_bundle(Path(__file__).parent / "fixtures" / "simulation.yaml")
    assert bundle.runtime is None

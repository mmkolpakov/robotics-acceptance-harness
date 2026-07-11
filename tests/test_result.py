from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from junitparser import JUnitXml
from robotics_runtime_contracts import validate_document

from robotics_acceptance_harness.documents import load_bundle
from robotics_acceptance_harness.metrics import AssertionEvaluation
from robotics_acceptance_harness.readiness import (
    GraphSnapshot,
    ReadinessResult,
    TopicObservation,
)
from robotics_acceptance_harness.result import (
    build_acceptance_result,
    write_junit_xml,
    write_result_json,
)
from robotics_acceptance_harness.timing import TimingObservation

FIXTURES = Path(__file__).parent / "fixtures" / "v2"


def result_inputs() -> dict[str, object]:
    snapshot = GraphSnapshot(
        observed_at_ns=2_000_000_000,
        topics={
            "/clock": TopicObservation(
                types=("rosgraph_msgs/msg/Clock",),
                publishers=1,
                subscribers=1,
                first_message_at_ns=1_000_000_000,
            )
        },
    )
    return {
        "result_id": "org.example.physics-smoke-001",
        "bundle": load_bundle(
            FIXTURES / "simulation.yaml",
            runtime_path=FIXTURES / "runtime.yaml",
        ),
        "readiness": ReadinessResult(snapshot, 1_000_000_000, 1.0),
        "timing": TimingObservation(True, 0, 0, 0.99, 0, 0, 10),
        "started_at": datetime(2026, 7, 11, 12, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 7, 11, 12, 0, tzinfo=UTC) + timedelta(seconds=30),
        "monotonic_duration_sec": 30,
        "shutdown": {
            "observer_detached": True,
            "recorders_closed": True,
            "evidence_index_finalized": True,
        },
    }


def test_build_result_validates_no_inference_execution() -> None:
    result = build_acceptance_result(assertions=(), **result_inputs())
    validate_document(result)
    assert result["status"] == "passed"
    assert result["workload"] == {"kind": "none"}


def test_json_and_junit_outputs_share_the_same_status(tmp_path: Path) -> None:
    evaluation = AssertionEvaluation("latency", "failed", 120.0, "ms", "threshold lte 100")
    result = build_acceptance_result(assertions=(evaluation,), **result_inputs())

    json_path = write_result_json(result, tmp_path / "acceptance-result.json")
    junit_path = write_junit_xml(result, tmp_path / "junit.xml")

    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "failed"
    xml = JUnitXml.fromfile(junit_path)
    assert xml.failures == 1
    assert xml.errors == 0

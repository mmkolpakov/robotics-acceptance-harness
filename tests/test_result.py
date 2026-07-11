from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from os import name as os_name
from pathlib import Path

import yaml
from junitparser import JUnitXml
from robotics_runtime_contracts import validate_document

from robotics_acceptance_harness.documents import load_bundle
from robotics_acceptance_harness.evidence import load_evidence_index
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


def test_result_links_only_verified_evidence(tmp_path: Path) -> None:
    segment = tmp_path / "run.mcap"
    segment.write_bytes(b"evidence")
    local_path = segment.as_posix()
    if os_name == "nt":
        local_path = f"/{local_path}"
    index = {
        "schema_version": "evidence-index.v1",
        "run_id": "org.example.physics-smoke-001",
        "generated_at": "2026-07-11T12:01:00Z",
        "finalized": True,
        "segments": [
            {
                "uri": segment.as_uri(),
                "local_path": local_path,
                "media_type": "application/mcap",
                "sha256": sha256(segment.read_bytes()).hexdigest(),
                "size_bytes": segment.stat().st_size,
                "retention_class": "pull-request-7d",
                "segment_index": 0,
                "upload_status": "local",
                "checksum_verified": True,
            }
        ],
    }
    index_path = tmp_path / "evidence-index.yaml"
    index_path.write_text(yaml.safe_dump(index), encoding="utf-8")
    verified = load_evidence_index(index_path)

    result = build_acceptance_result(
        assertions=(),
        evidence_index=verified,
        **result_inputs(),
    )

    assert result["evidence"][0]["uri"] == segment.as_uri()
    assert "local_path" not in result["evidence"][0]

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from os import name as os_name
from pathlib import Path

import pytest
import yaml
from junitparser import JUnitXml
from robotics_runtime_contracts import validate_document

from robotics_acceptance_harness.documents import load_bundle
from robotics_acceptance_harness.evidence import load_evidence_index
from robotics_acceptance_harness.forbidden_graph import ForbiddenGraphObservation
from robotics_acceptance_harness.metrics import AssertionEvaluation
from robotics_acceptance_harness.readiness import (
    EndpointObservation,
    GraphSnapshot,
    ReadinessResult,
    TopicObservation,
)
from robotics_acceptance_harness.result import (
    build_acceptance_result,
    build_acceptance_result_v3,
    build_acceptance_result_v4,
    write_junit_xml,
    write_result_json,
)
from robotics_acceptance_harness.time_authority import TimeAuthorityObservation
from robotics_acceptance_harness.timing import TimingObservation

FIXTURES = Path(__file__).parent / "fixtures" / "simulation"


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
            FIXTURES / "scenario.yaml",
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
        "forbidden_graph": ForbiddenGraphObservation((), (), (), ()),
    }


def test_build_result_validates_no_inference_execution() -> None:
    result = build_acceptance_result(assertions=(), **result_inputs())
    validate_document(result)
    assert result["status"] == "passed"
    assert result["workload"] == {"kind": "none"}


def test_result_omits_endpoints_that_lost_their_type() -> None:
    snapshot = GraphSnapshot(
        observed_at_ns=2_000_000_000,
        topics={
            "/clock": TopicObservation(
                types=(),
                publishers=1,
                subscribers=1,
                first_message_at_ns=1_000_000_000,
            )
        },
        services={"/reset": EndpointObservation(types=(), servers=1)},
        actions={"/move": EndpointObservation(types=(), servers=1, clients=1)},
    )
    inputs = result_inputs()
    inputs["readiness"] = ReadinessResult(snapshot, 1_000_000_000, 1.0)

    result = build_acceptance_result(assertions=(), **inputs)

    assert result["observed_ros_graph"]["topics"] == []
    assert result["observed_ros_graph"]["services"] == []
    assert result["observed_ros_graph"]["actions"] == []
    validate_document(result)


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


def test_v2_result_rejects_evidence_from_another_run(tmp_path: Path) -> None:
    segment = tmp_path / "metrics.json"
    segment.write_bytes(b"evidence")
    local_path = segment.as_posix()
    if os_name == "nt":
        local_path = f"/{local_path}"
    index_path = tmp_path / "evidence-index.yaml"
    index_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "evidence-index.v1",
                "run_id": "run-00000000-0000-4000-8000-000000000001",
                "generated_at": "2026-07-11T12:01:00Z",
                "finalized": True,
                "segments": [
                    {
                        "uri": segment.as_uri(),
                        "local_path": local_path,
                        "media_type": "application/json",
                        "sha256": sha256(segment.read_bytes()).hexdigest(),
                        "size_bytes": segment.stat().st_size,
                        "retention_class": "pull-request-7d",
                        "segment_index": 0,
                        "upload_status": "local",
                        "checksum_verified": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence = load_evidence_index(index_path)
    inputs = result_inputs()
    inputs.pop("result_id")

    with pytest.raises(ValueError, match="evidence index run_id"):
        build_acceptance_result_v3(
            result_id="result-00000000-0000-4000-8000-000000000001",
            run_id="run-00000000-0000-4000-8000-000000000002",
            domain_id="camera-domain",
            time_authority=TimeAuthorityObservation(
                source_id="simulation-clock",
                measurement_kind="clock_offset",
                sample_count=30,
                window_start_ns=1,
                window_end_ns=2,
                p50_ms=0,
                p95_ms=0,
                max_ms=0,
                within_policy=True,
            ),
            time_authority_evidence_sha256="f" * 64,
            assertions=(),
            unevaluated=(),
            evidence_index=evidence,
            **inputs,
        )


def test_run_scoped_result_can_mark_time_authority_as_unevaluated(
    tmp_path: Path,
) -> None:
    run_id = "run-00000000-0000-4000-8000-000000000002"
    segment = tmp_path / "probe.json"
    segment.write_bytes(b"{}")
    local_path = segment.as_posix()
    if os_name == "nt":
        local_path = f"/{local_path}"
    index_path = tmp_path / "evidence-index.yaml"
    index_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "evidence-index.v1",
                "run_id": run_id,
                "generated_at": "2026-07-11T12:01:00Z",
                "finalized": True,
                "segments": [
                    {
                        "uri": segment.as_uri(),
                        "local_path": local_path,
                        "media_type": "application/json",
                        "sha256": sha256(segment.read_bytes()).hexdigest(),
                        "size_bytes": segment.stat().st_size,
                        "retention_class": "pull-request-7d",
                        "segment_index": 0,
                        "upload_status": "local",
                        "checksum_verified": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    inputs = result_inputs()
    inputs.pop("result_id")

    result = build_acceptance_result_v4(
        result_id="result-00000000-0000-4000-8000-000000000001",
        run_id=run_id,
        domain_id="camera-domain",
        time_authority=TimeAuthorityObservation(
            source_id="external-clock",
            measurement_kind="delivery_latency",
            sample_count=0,
            window_start_ns=0,
            window_end_ns=0,
            p50_ms=0,
            p95_ms=0,
            max_ms=0,
            within_policy=False,
        ),
        time_authority_evidence_sha256=None,
        assertions=(),
        unevaluated=("$.clock_observation", "$.time_authority_observation"),
        evidence_index=load_evidence_index(index_path),
        **inputs,
    )

    assert result["status"] == "incomplete"
    authority = result["time_authority_observation"]
    assert result["schema_version"] == "acceptance-result.v4"
    assert authority["p50_delivery_latency_ms"] == 0
    assert authority["within_policy"] is False
    assert "evidence_sha256" not in authority

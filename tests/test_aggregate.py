from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from os import name as os_name
from pathlib import Path
from typing import Any

import pytest

from robotics_acceptance_harness.aggregate import (
    aggregate_results,
    evaluate_trace_aggregate,
    evaluate_transport_qualification,
)
from robotics_acceptance_harness.documents import BundleValidationError, load_bundle, load_document
from robotics_acceptance_harness.evidence import load_evidence_index
from robotics_acceptance_harness.forbidden_graph import ForbiddenGraphObservation
from robotics_acceptance_harness.metrics import AssertionEvaluation
from robotics_acceptance_harness.readiness import GraphSnapshot, ReadinessResult
from robotics_acceptance_harness.result import (
    build_acceptance_result_v4,
    write_result_json,
)
from robotics_acceptance_harness.time_authority import TimeAuthorityObservation
from robotics_acceptance_harness.timing import TimingObservation
from robotics_acceptance_harness.traces import TraceInputError

FIXTURES = Path(__file__).parent / "fixtures" / "simulation"
RUN_ID = "run-01234567-89ab-4def-8123-456789abcdef"
TRACE_ID = "01" * 16
TYPE_HASH = f"RIHS01_{'1' * 64}"


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def result(
    tmp_path: Path,
    domain_id: str,
    suffix: str,
    *,
    assertion_status: str = "passed",
    unevaluated: tuple[str, ...] = (),
    time_authority_within_policy: bool = True,
) -> Path:
    bundle = load_bundle(
        FIXTURES / "scenario.yaml",
        runtime_path=FIXTURES / "runtime.yaml",
    )
    evidence_payload_path = write_json(
        tmp_path / f"metrics-{suffix}.json",
        {"domain_id": domain_id},
    )
    evidence_payload = evidence_payload_path.read_bytes()
    local_path = evidence_payload_path.resolve().as_posix()
    if os_name == "nt":
        local_path = f"/{local_path}"
    evidence_digest = hashlib.sha256(evidence_payload).hexdigest()
    evidence_path = write_json(
        tmp_path / f"evidence-{suffix}.json",
        {
            "schema_version": "evidence-index.v2",
            "run_id": RUN_ID,
            "generated_at": "2026-07-26T12:00:00Z",
            "finalized": True,
            "policy_observation": {
                "recording_mode": "bounded",
                "compression": "zstd",
                "upload_mode": "local_only",
                "remote_sink_used": False,
                "spool_peak_size_bytes": len(evidence_payload),
                "upload_lag_max_sec": 0,
            },
            "segments": [
                {
                    "uri": evidence_payload_path.resolve().as_uri(),
                    "local_path": local_path,
                    "media_type": "application/x-ndjson",
                    "sha256": evidence_digest,
                    "size_bytes": len(evidence_payload),
                    "retention_class": "pull-request-7d",
                    "segment_index": 0,
                    "upload_status": "local",
                    "checksum_verified": True,
                }
            ],
        },
    )
    document = build_acceptance_result_v4(
        result_id=f"result-01234567-89ab-4def-8123-456789abcde{suffix}",
        run_id=RUN_ID,
        domain_id=domain_id,
        bundle=bundle,
        readiness=ReadinessResult(GraphSnapshot(1), 1, 0),
        timing=TimingObservation(True, 0, 0, 1, 0, 0, 1),
        time_authority=TimeAuthorityObservation(
            "simulation-clock",
            "delivery_latency",
            30,
            1,
            30,
            0,
            0,
            0,
            time_authority_within_policy,
        ),
        time_authority_evidence_sha256=evidence_digest,
        assertions=(
            AssertionEvaluation(
                assertion_id="domain-smoke",
                status=assertion_status,
                observed_value=1,
                unit="1",
            ),
        ),
        unevaluated=unevaluated,
        started_at=datetime(2026, 7, 26, 12, tzinfo=UTC),
        finished_at=datetime(2026, 7, 26, 12, 1, tzinfo=UTC),
        monotonic_duration_sec=60,
        shutdown={
            "observer_detached": True,
            "recorders_closed": True,
            "evidence_index_finalized": True,
        },
        evidence_index=load_evidence_index(evidence_path),
        forbidden_graph=ForbiddenGraphObservation((), (), (), ()),
    )
    assert document["schema_version"] == "acceptance-result.v4"
    return write_result_json(document, tmp_path / f"result-{suffix}.json")


def run_context(tmp_path: Path) -> Path:
    bundle = load_bundle(
        FIXTURES / "scenario.yaml",
        runtime_path=FIXTURES / "runtime.yaml",
    )
    return write_json(
        tmp_path / "acceptance-run.json",
        {
            "schema_version": "acceptance-run.v1",
            "run_id": RUN_ID,
            "created_at": "2026-07-26T12:00:00Z",
            "scenario_id": bundle.scenario.data["scenario_id"],
            "scenario_sha256": bundle.scenario.sha256,
            "time_authority": {
                "kind": "sim_clock",
                "source_id": "simulation-clock",
            },
            "domains": [
                {"domain_id": "camera-domain", "role": "sensor"},
                {"domain_id": "control-domain", "role": "controller"},
            ],
        },
    )


def base_aggregate(tmp_path: Path, context_path: Path) -> Path:
    return aggregate_results(
        run_context_path=context_path,
        result_paths=[
            result(tmp_path, "camera-domain", "0"),
            result(tmp_path, "control-domain", "1"),
        ],
        output_path=tmp_path / "aggregate-v1.json",
        aggregate_id="aggregate-01234567-89ab-4def-8123-456789abcdea",
        generated_at=datetime(2026, 7, 26, 12, 2, tzinfo=UTC),
    )


def trace_file(
    tmp_path: Path,
    domain_id: str,
    span_name: str,
    span_byte: int,
    *,
    message_id: str = "message-1",
    parent_byte: int | None = None,
    link_byte: int | None = None,
) -> Path:
    span: dict[str, object] = {
        "traceId": TRACE_ID,
        "spanId": f"{span_byte:02x}" * 8,
        "name": span_name,
        "kind": 1,
        "startTimeUnixNano": (
            "1785067200000003000"
            if parent_byte is not None or link_byte is not None
            else "1785067200000001000"
        ),
        "endTimeUnixNano": (
            "1785067200000004000"
            if parent_byte is not None or link_byte is not None
            else "1785067200000002000"
        ),
        "attributes": [
            {
                "key": "messaging.message.id",
                "value": {"stringValue": message_id},
            }
        ],
    }
    if parent_byte is not None:
        span["parentSpanId"] = f"{parent_byte:02x}" * 8
    if link_byte is not None:
        span["links"] = [
            {
                "traceId": TRACE_ID,
                "spanId": f"{link_byte:02x}" * 8,
                "attributes": [
                    {
                        "key": "messaging.message.id",
                        "value": {"stringValue": message_id},
                    }
                ],
            }
        ]
    return write_json(
        tmp_path / f"{domain_id}.traces.jsonl",
        {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "run.id",
                                "value": {"stringValue": RUN_ID},
                            },
                            {
                                "key": "domain.id",
                                "value": {"stringValue": domain_id},
                            },
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "robotics.test"},
                            "spans": [span],
                        }
                    ],
                }
            ]
        },
    )


def trace_evidence_index(tmp_path: Path, domain_id: str, trace_path: Path) -> Path:
    local_path = trace_path.resolve().as_posix()
    if os_name == "nt":
        local_path = f"/{local_path}"
    payload = trace_path.read_bytes()
    return write_json(
        tmp_path / f"{domain_id}.evidence.json",
        {
            "schema_version": "evidence-index.v2",
            "run_id": RUN_ID,
            "generated_at": "2026-07-26T12:00:00Z",
            "finalized": True,
            "policy_observation": {
                "recording_mode": "bounded",
                "compression": "zstd",
                "upload_mode": "local_only",
                "remote_sink_used": False,
                "spool_peak_size_bytes": 0,
                "upload_lag_max_sec": 0,
            },
            "segments": [
                {
                    "uri": trace_path.resolve().as_uri(),
                    "local_path": local_path,
                    "media_type": "application/x-ndjson",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                    "retention_class": "pull-request-7d",
                    "segment_index": 900000,
                    "upload_status": "local",
                    "checksum_verified": True,
                }
            ],
        },
    )


def channel_contract(tmp_path: Path, relationship: str = "link") -> Path:
    return write_json(
        tmp_path / "channel.json",
        {
            "schema_version": "zenoh-channel.v1",
            "channel_id": "sensor.control",
            "source": {
                "domain_id": "camera-domain",
                "ros_domain_id": 10,
                "topic": "/observations",
                "message_type": "example_interfaces/msg/String",
                "type_hash": TYPE_HASH,
            },
            "destination": {
                "domain_id": "control-domain",
                "ros_domain_id": 20,
                "topic": "/observations",
                "message_type": "example_interfaces/msg/String",
                "type_hash": TYPE_HASH,
            },
            "bridge": {
                "implementation": "zenoh-bridge-ros2dds",
                "version": "1.9.0",
                "configuration_sha256": "2" * 64,
                "dds_discovery_scope": "local_domain_only",
                "zenoh_key_expression": "robotics/observations",
            },
            "qos": {
                "reliability": "reliable",
                "durability": "volatile",
                "history": "keep_last",
                "depth": 10,
                "liveliness": "automatic",
                "liveliness_lease_duration_ms": "infinite",
                "deadline_ms": 100,
                "lifespan_ms": 500,
            },
            "delivery": {
                "observation_window_sec": 30,
                "minimum_source_messages": 1,
                "message_id_attribute": "messaging.message.id",
                "max_loss_ratio": 0,
                "max_duplicate_count": 0,
                "max_out_of_order_count": 0,
                "max_message_age_ms": 100,
            },
            "trace": {
                "carrier_field": "trace_context",
                "relationship": relationship,
                "producer_span_name": "observation publish",
                "consumer_span_name": "observation receive",
            },
        },
    )


def causal_chain(
    tmp_path: Path,
    channel_path: Path,
    *,
    chain_id: str = "sensor-to-control",
    filename: str = "causal-chain.json",
) -> Path:
    return write_json(
        tmp_path / filename,
        {
            "schema_version": "causal-chain.v1",
            "chain_id": chain_id,
            "required_domain_ids": ["camera-domain", "control-domain"],
            "channel_contracts": [
                {
                    "channel_id": "sensor.control",
                    "sha256": hashlib.sha256(channel_path.read_bytes()).hexdigest(),
                }
            ],
            "require_connected_trace_graph": True,
            "missing_evidence_status": "incomplete",
            "broken_relationship_status": "failed",
        },
    )


def trace_aggregate(
    tmp_path: Path,
    *,
    relationship: str,
    consumer_parent: int | None = None,
    consumer_link: int | None = None,
    consumer_span_byte: int = 3,
    consumer_message_id: str = "message-1",
    chain_count: int = 1,
) -> dict[str, object]:
    context_path = run_context(tmp_path)
    producer = trace_file(
        tmp_path,
        "camera-domain",
        "observation publish",
        2,
    )
    consumer = trace_file(
        tmp_path,
        "control-domain",
        "observation receive",
        consumer_span_byte,
        message_id=consumer_message_id,
        parent_byte=consumer_parent,
        link_byte=consumer_link,
    )
    channel_path = channel_contract(tmp_path, relationship)
    chain_paths = [causal_chain(tmp_path, channel_path)]
    if chain_count == 2:
        chain_paths.append(
            causal_chain(
                tmp_path,
                channel_path,
                chain_id="sensor-to-control-audit",
                filename="causal-chain-audit.json",
            )
        )
    output = evaluate_trace_aggregate(
        run_context_path=context_path,
        base_aggregate_path=base_aggregate(tmp_path, context_path),
        causal_chain_paths=chain_paths,
        channel_contract_paths=[channel_path],
        trace_paths={
            "camera-domain": producer,
            "control-domain": consumer,
        },
        evidence_index_paths={
            "camera-domain": trace_evidence_index(tmp_path, "camera-domain", producer),
            "control-domain": trace_evidence_index(tmp_path, "control-domain", consumer),
        },
        observation_output_dir=tmp_path / "observations",
        output_path=tmp_path / "aggregate-v2.json",
        aggregate_id="aggregate-01234567-89ab-4def-8123-456789abcdef",
        generated_at=datetime(2026, 7, 26, 12, 3, tzinfo=UTC),
    )
    return json.loads(output.read_text(encoding="utf-8"))


def transport_qualification(
    tmp_path: Path,
    *,
    relationship: str,
    consumer_link: int | None = None,
    consumer_message_id: str = "message-1",
) -> dict[str, object]:
    producer = trace_file(
        tmp_path,
        "camera-domain",
        "observation publish",
        2,
    )
    consumer = trace_file(
        tmp_path,
        "control-domain",
        "observation receive",
        3,
        message_id=consumer_message_id,
        link_byte=consumer_link,
    )
    channel_path = channel_contract(tmp_path, relationship)
    output = evaluate_transport_qualification(
        run_id=RUN_ID,
        causal_chain_paths=[causal_chain(tmp_path, channel_path)],
        channel_contract_paths=[channel_path],
        trace_paths={
            "camera-domain": producer,
            "control-domain": consumer,
        },
        evidence_index_paths={
            "camera-domain": trace_evidence_index(tmp_path, "camera-domain", producer),
            "control-domain": trace_evidence_index(tmp_path, "control-domain", consumer),
        },
        observation_output_dir=tmp_path / "transport-observations",
        output_path=tmp_path / "transport-qualification.json",
        qualification_id="qualification-01234567-89ab-4def-8123-456789abcdef",
        generated_at=datetime(2026, 7, 26, 12, 3, tzinfo=UTC),
    )
    return json.loads(output.read_text(encoding="utf-8"))


def test_aggregate_requires_and_emits_every_registered_domain(tmp_path: Path) -> None:
    context_path = run_context(tmp_path)
    output = base_aggregate(tmp_path, context_path)

    aggregate = json.loads(output.read_text(encoding="utf-8"))
    assert aggregate["per_domain_aggregate"] == "passed"
    assert [item["domain_id"] for item in aggregate["per_domain_results"]] == [
        "camera-domain",
        "control-domain",
    ]
    assert aggregate["cross_domain_e2e"]["status"] == "unevaluated"


def test_aggregate_reads_legacy_v2_result_during_migration(tmp_path: Path) -> None:
    context_path = run_context(tmp_path)
    legacy_path = result(tmp_path, "camera-domain", "0")
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    legacy["schema_version"] = "acceptance-result.v2"
    authority = legacy["time_authority_observation"]
    authority["p50_offset_ms"] = authority.pop("p50_delivery_latency_ms")
    authority["p95_offset_ms"] = authority.pop("p95_delivery_latency_ms")
    authority["max_offset_ms"] = authority.pop("max_delivery_latency_ms")
    legacy["evidence"][0]["media_type"] = "application/json"
    write_result_json(legacy, legacy_path)

    output = aggregate_results(
        run_context_path=context_path,
        result_paths=[legacy_path, result(tmp_path, "control-domain", "1")],
        output_path=tmp_path / "aggregate.json",
    )

    assert load_document(output).data["per_domain_aggregate"] == "passed"


def test_aggregate_fails_when_registered_domain_has_no_result(tmp_path: Path) -> None:
    with pytest.raises(BundleValidationError, match="control-domain"):
        aggregate_results(
            run_context_path=run_context(tmp_path),
            result_paths=[result(tmp_path, "camera-domain", "0")],
            output_path=tmp_path / "aggregate.json",
        )


@pytest.mark.parametrize("assertion_status", ["error", "failed"])
def test_unevaluated_does_not_mask_known_failure(
    tmp_path: Path,
    assertion_status: str,
) -> None:
    result_path = result(
        tmp_path,
        "camera-domain",
        "0",
        assertion_status=assertion_status,
        unevaluated=("$.assertions.pending",),
    )

    document = json.loads(result_path.read_text(encoding="utf-8"))

    assert document["status"] == assertion_status


def test_unevaluated_does_not_mask_time_authority_failure(tmp_path: Path) -> None:
    result_path = result(
        tmp_path,
        "camera-domain",
        "0",
        unevaluated=("$.assertions.pending",),
        time_authority_within_policy=False,
    )

    document = json.loads(result_path.read_text(encoding="utf-8"))

    assert document["status"] == "failed"


def test_aggregate_rejects_result_changed_after_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context_path = run_context(tmp_path)
    camera_result = result(tmp_path, "camera-domain", "0")
    control_result = result(tmp_path, "control-domain", "1")
    original_load_document = load_document
    calls = 0

    def load_and_mutate(path: str | Path, **kwargs: Any) -> Any:
        nonlocal calls
        document = original_load_document(path, **kwargs)
        calls += 1
        if calls == 3:
            camera_result.write_text("{}\n", encoding="utf-8")
        return document

    monkeypatch.setattr(
        "robotics_acceptance_harness.aggregate.load_document",
        load_and_mutate,
    )

    with pytest.raises(BundleValidationError, match="changed during aggregation"):
        aggregate_results(
            run_context_path=context_path,
            result_paths=[camera_result, control_result],
            output_path=tmp_path / "aggregate.json",
        )


def test_trace_aggregate_proves_span_link(tmp_path: Path) -> None:
    aggregate = trace_aggregate(
        tmp_path,
        relationship="link",
        consumer_link=2,
    )

    assert aggregate["schema_version"] == "acceptance-aggregate.v2"
    assert aggregate["cross_domain_e2e"]["status"] == "passed"
    assert aggregate["causal_chains"][0]["root_trace_id"] == TRACE_ID
    assert aggregate["causal_chains"][0]["hops"][0]["relationship"] == "link"
    assert aggregate["channel_observations"][0]["status"] == "passed"
    channel = aggregate["channel_contracts"][0]
    assert channel["source_domain_id"] == "camera-domain"
    assert channel["destination_domain_id"] == "control-domain"


def test_transport_qualification_passes_without_domain_execution(tmp_path: Path) -> None:
    result = transport_qualification(
        tmp_path,
        relationship="link",
        consumer_link=2,
    )

    assert result["schema_version"] == "transport-qualification-result.v1"
    assert result["verdict"]["status"] == "passed"
    assert "acceptance_run_sha256" not in result
    assert "per_domain_results" not in result
    assert result["channel_observations"][0]["status"] == "passed"


def test_transport_qualification_fails_measured_delivery_loss(tmp_path: Path) -> None:
    result = transport_qualification(
        tmp_path,
        relationship="link",
        consumer_link=2,
        consumer_message_id="message-2",
    )

    assert result["verdict"]["status"] == "failed"
    assert result["channel_observations"][0]["status"] == "failed"


def test_trace_aggregate_proves_parent_chain(tmp_path: Path) -> None:
    aggregate = trace_aggregate(
        tmp_path,
        relationship="parent",
        consumer_parent=2,
    )

    assert aggregate["cross_domain_e2e"]["status"] == "passed"
    assert aggregate["causal_chains"][0]["hops"][0]["relationship"] == "parent"


def test_trace_aggregate_evaluates_multiple_declared_chains(tmp_path: Path) -> None:
    aggregate = trace_aggregate(
        tmp_path,
        relationship="link",
        consumer_link=2,
        chain_count=2,
    )

    assert aggregate["cross_domain_e2e"]["status"] == "passed"
    assert aggregate["cross_domain_e2e"]["chain_count"] == 2
    assert aggregate["cross_domain_e2e"]["passed_chain_count"] == 2
    assert len(aggregate["causal_chain_contracts"]) == 2


def test_trace_aggregate_rejects_span_identity_reused_across_domains(
    tmp_path: Path,
) -> None:
    with pytest.raises(TraceInputError, match="appears in domains"):
        trace_aggregate(
            tmp_path,
            relationship="link",
            consumer_link=2,
            consumer_span_byte=2,
        )


def test_trace_aggregate_fails_on_broken_span_link(tmp_path: Path) -> None:
    aggregate = trace_aggregate(
        tmp_path,
        relationship="link",
        consumer_link=4,
    )

    assert aggregate["cross_domain_e2e"]["status"] == "failed"
    assert aggregate["causal_chains"][0]["status"] == "failed"
    violations = aggregate["causal_chains"][0]["violations"]
    assert violations[0]["code"] == "relationship_mismatch"


def test_trace_aggregate_writes_contract_valid_failed_channel_observation(
    tmp_path: Path,
) -> None:
    aggregate = trace_aggregate(
        tmp_path,
        relationship="link",
        consumer_link=2,
        consumer_message_id="message-2",
    )

    assert aggregate["cross_domain_e2e"]["status"] == "failed"
    observation = json.loads(
        (tmp_path / "observations" / "sensor.control.json").read_text(encoding="utf-8")
    )
    assert observation["status"] == "failed"
    assert {item["code"] for item in observation["violations"]} == {
        "duplicate_count_exceeded",
        "loss_ratio_exceeded",
    }
    assert all("channel_id" not in item for item in observation["violations"])

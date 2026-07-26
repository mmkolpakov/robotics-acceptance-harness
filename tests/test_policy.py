from __future__ import annotations

import json
from hashlib import sha256
from os import name as os_name
from pathlib import Path

from robotics_acceptance_harness.evidence import load_evidence_index
from robotics_acceptance_harness.metrics import MetricSample
from robotics_acceptance_harness.policy import (
    evaluate_data_plane_policy,
    evaluate_evidence_policy,
)

RUN_ID = "run-01234567-89ab-4def-8123-456789abcdef"


def local_path(path: Path) -> str:
    value = path.as_posix()
    return f"/{value}" if os_name == "nt" else value


def evidence(tmp_path: Path, *, topic: str = "/camera/image"):
    segment = tmp_path / "run_0.mcap"
    segment.write_bytes(b"mcap")
    segment_sha = sha256(segment.read_bytes()).hexdigest()
    summary = tmp_path / "run_0.mcap-summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": "mcap-summary.v1",
                "source_sha256": segment_sha,
                "compressions": ["zstd"],
                "statistics": {
                    "message_count": 10,
                    "schema_count": 1,
                    "channel_count": 1,
                    "attachment_count": 0,
                    "metadata_count": 1,
                    "chunk_count": 1,
                    "message_start_time_ns": 1,
                    "message_end_time_ns": 2_000_000_001,
                },
                "channels": [
                    {
                        "topic": topic,
                        "message_encoding": "cdr",
                        "schema_name": "sensor_msgs/msg/Image",
                        "message_count": 10,
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    index = tmp_path / "evidence-index.json"
    index.write_text(
        json.dumps(
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
                    "spool_peak_size_bytes": 4,
                    "upload_lag_max_sec": 0,
                },
                "segments": [
                    {
                        "uri": segment.as_uri(),
                        "local_path": local_path(segment),
                        "media_type": "application/mcap",
                        "sha256": segment_sha,
                        "size_bytes": segment.stat().st_size,
                        "retention_class": "pull-request-7d",
                        "segment_index": 0,
                        "upload_status": "local",
                        "checksum_verified": True,
                        "mcap_summary": {
                            "uri": summary.as_uri(),
                            "sha256": sha256(summary.read_bytes()).hexdigest(),
                            "size_bytes": summary.stat().st_size,
                            "media_type": "application/vnd.robotics.mcap-summary.v1+json",
                        },
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return load_evidence_index(index)


def evidence_policy() -> dict[str, object]:
    return {
        "topics": ["/camera/image"],
        "recording_mode": "bounded",
        "compression": "zstd",
        "max_segment_size_bytes": 1024,
        "max_segment_duration_sec": 60,
        "max_spool_size_bytes": 1024,
        "spool_high_watermark_ratio": 0.85,
        "max_upload_lag_sec": 10,
        "upload_mode": "local_only",
        "retention_class": "pull-request-7d",
        "remote_sink_allowed": False,
    }


def test_evidence_policy_checks_channel_coverage_from_verified_summary(tmp_path: Path) -> None:
    evaluations = evaluate_evidence_policy(evidence_policy(), evidence(tmp_path))

    assert all(item.status == "passed" for item in evaluations)


def test_evidence_policy_fails_when_required_channel_is_absent(tmp_path: Path) -> None:
    evaluations = evaluate_evidence_policy(
        evidence_policy(),
        evidence(tmp_path, topic="/other"),
    )

    channel = next(item for item in evaluations if item.assertion_id == "policy-evidence-topics")
    assert channel.status == "failed"
    assert "/camera/image" in channel.message


def test_data_plane_policy_checks_static_transport_and_attributed_metrics() -> None:
    policy = {
        "max_message_age_ms": 100,
        "max_loss_ratio": 0,
        "shm_transport": True,
        "data_sharing": False,
        "private_ipc": True,
    }
    runtime = {
        "data_plane": {
            "shm_transport": True,
            "data_sharing": False,
            "private_ipc": False,
        }
    }
    samples = [
        MetricSample("robotics.message.age", 20, "ms", 1, {"domain.id": "camera"}),
        MetricSample("robotics.message.loss_ratio", 0, "1", 1, {"domain.id": "camera"}),
    ]

    evaluations = evaluate_data_plane_policy(
        policy,
        runtime,
        samples,
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=2,
    )

    static = next(item for item in evaluations if item.assertion_id == "data-plane-private-ipc")
    assert static.status == "failed"
    assert all(
        item.status == "passed"
        for item in evaluations
        if item.assertion_id in {"data-plane-message-age", "data-plane-loss-ratio"}
    )

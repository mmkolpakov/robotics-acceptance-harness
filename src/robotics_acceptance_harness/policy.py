from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from robotics_acceptance_harness.evidence import VerifiedEvidence
from robotics_acceptance_harness.metrics import (
    AssertionEvaluation,
    MetricSample,
    evaluate_metric_assertions,
)


def _boolean_evaluation(assertion_id: str, passed: bool, message: str) -> AssertionEvaluation:
    return AssertionEvaluation(
        assertion_id=assertion_id,
        status="passed" if passed else "failed",
        observed_value=1 if passed else 0,
        unit="1",
        message="" if passed else message,
    )


def evaluate_data_plane_policy(
    policy: Mapping[str, Any],
    runtime: Mapping[str, Any],
    samples: Sequence[MetricSample],
    *,
    domain_id: str,
    window_start_ns: int,
    window_end_ns: int,
) -> tuple[AssertionEvaluation, ...]:
    """Evaluate static transport facts and attributed data-plane telemetry."""

    observed = runtime["data_plane"]
    evaluations = [
        _boolean_evaluation(
            f"data-plane-{field.replace('_', '-')}",
            observed.get(field) == policy[field],
            f"expected {field}={policy[field]!r}; observed {observed.get(field)!r}",
        )
        for field in ("shm_transport", "data_sharing", "private_ipc")
    ]
    if "fastdds_profile_sha256" in policy:
        evaluations.append(
            _boolean_evaluation(
                "data-plane-fastdds-profile",
                observed.get("fastdds_profile_sha256") == policy["fastdds_profile_sha256"],
                "Fast DDS profile digest differs",
            )
        )
    metric_assertions = (
        {
            "assertion_id": "data-plane-message-age",
            "metric_name": "robotics.message.age",
            "unit": "ms",
            "aggregation": "p95",
            "operator": "lte",
            "threshold": policy["max_message_age_ms"],
            "window_sec": 86_400,
            "attribute_match": {"domain.id": domain_id},
        },
        {
            "assertion_id": "data-plane-loss-ratio",
            "metric_name": "robotics.message.loss_ratio",
            "unit": "1",
            "aggregation": "max",
            "operator": "lte",
            "threshold": policy["max_loss_ratio"],
            "window_sec": 86_400,
            "attribute_match": {"domain.id": domain_id},
        },
    )
    evaluations.extend(
        evaluate_metric_assertions(
            metric_assertions,
            samples,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
        )
    )
    return tuple(evaluations)


def evaluate_evidence_policy(
    policy: Mapping[str, Any],
    evidence: VerifiedEvidence,
) -> tuple[AssertionEvaluation, ...]:
    """Evaluate recording coverage and bounded-storage policy from v2 evidence."""

    if evidence.index.schema_version != "evidence-index.v2":
        return (
            AssertionEvaluation(
                assertion_id="evidence-index-version",
                status="error",
                observed_value=None,
                unit="1",
                message="evidence-index.v2 is required",
            ),
        )

    observation = evidence.index.data["policy_observation"]
    segments = evidence.index.data["segments"]
    summaries = evidence.mcap_summaries
    channels = {
        channel["topic"]
        for summary in summaries
        for channel in summary.data["channels"]
        if channel["message_count"] > 0
    }
    required_topics = set(policy["topics"])
    durations_sec = [
        (
            summary.data["statistics"]["message_end_time_ns"]
            - summary.data["statistics"]["message_start_time_ns"]
        )
        / 1_000_000_000
        for summary in summaries
    ]
    compressions = {
        compression for summary in summaries for compression in summary.data["compressions"]
    }
    max_segment_size = max((segment["size_bytes"] for segment in segments), default=0)
    max_segment_duration = max(durations_sec, default=0.0)
    retention_classes = {segment["retention_class"] for segment in segments}
    expected_remote = policy["upload_mode"] == "closed_segments_during_run"
    spool_ratio = observation["spool_peak_size_bytes"] / policy["max_spool_size_bytes"]
    checks = (
        (
            "evidence-topics",
            required_topics <= channels,
            f"missing recorded topics: {sorted(required_topics - channels)}",
        ),
        (
            "evidence-recording-mode",
            observation["recording_mode"] == policy["recording_mode"],
            "recording mode differs",
        ),
        (
            "evidence-compression",
            compressions == {policy["compression"]}
            and observation["compression"] == policy["compression"],
            f"expected only {policy['compression']}; observed {sorted(compressions)}",
        ),
        (
            "evidence-segment-size",
            max_segment_size <= policy["max_segment_size_bytes"],
            "segment size limit exceeded",
        ),
        (
            "evidence-segment-duration",
            max_segment_duration <= policy["max_segment_duration_sec"],
            "segment duration limit exceeded",
        ),
        (
            "evidence-spool-size",
            observation["spool_peak_size_bytes"] <= policy["max_spool_size_bytes"],
            "spool size limit exceeded",
        ),
        (
            "evidence-spool-watermark",
            spool_ratio <= policy["spool_high_watermark_ratio"],
            "spool high-watermark ratio exceeded",
        ),
        (
            "evidence-upload-lag",
            observation["upload_lag_max_sec"] <= policy["max_upload_lag_sec"],
            "upload lag limit exceeded",
        ),
        (
            "evidence-upload-mode",
            observation["upload_mode"] == policy["upload_mode"],
            "upload mode differs",
        ),
        (
            "evidence-retention",
            retention_classes == {policy["retention_class"]},
            f"retention class differs: {sorted(retention_classes)}",
        ),
        (
            "evidence-remote-sink",
            observation["remote_sink_used"] == expected_remote
            and policy["remote_sink_allowed"] == expected_remote,
            "remote sink policy differs",
        ),
    )
    return tuple(
        _boolean_evaluation(f"policy-{name}", passed, message) for name, passed, message in checks
    )


__all__ = ["evaluate_data_plane_policy", "evaluate_evidence_policy"]

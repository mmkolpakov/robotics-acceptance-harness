from __future__ import annotations

from pathlib import Path

from robotics_acceptance_harness.evidence import load_evidence_index
from robotics_acceptance_harness.metrics import (
    HistogramSample,
    MetricSample,
    MetricTemporality,
)
from robotics_acceptance_harness.policy import (
    SEQUENCE_METHOD_ATTRIBUTE,
    SINGLE_PUBLISHER_SEQUENCE_METHOD,
    evaluate_data_plane_policy,
    evaluate_evidence_policy,
)
from tests.support import local_mcap_segment, write_evidence_index

RUN_ID = "run-01234567-89ab-4def-8123-456789abcdef"


def evidence(tmp_path: Path, *, topic: str = "/camera/image"):
    index = write_evidence_index(
        tmp_path / "evidence-index.json",
        run_id=RUN_ID,
        recording_mode="bounded",
        segments=[
            local_mcap_segment(
                tmp_path / "run_0.mcap",
                topics={topic: "sensor_msgs/msg/Image"},
            )
        ],
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


def data_plane_policy(
    *,
    max_loss_ratio: float = 0,
    shm_transport: bool = False,
) -> dict[str, object]:
    return {
        "max_message_age_ms": 100,
        "max_loss_ratio": max_loss_ratio,
        "shm_transport": shm_transport,
        "data_sharing": False,
        "private_ipc": True,
    }


def counter(
    name: str,
    value: float,
    observed_at_ns: int,
    *,
    temporality: MetricTemporality = "delta",
    start_time_ns: int = 0,
    unit: str = "{message}",
    channel: str = "/robotics/runtime_probe",
    sequence_method: str = SINGLE_PUBLISHER_SEQUENCE_METHOD,
) -> MetricSample:
    return MetricSample(
        name,
        value,
        unit,
        observed_at_ns,
        {
            "domain.id": "camera",
            "channel": channel,
            SEQUENCE_METHOD_ATTRIBUTE: sequence_method,
        },
        instrument_kind="sum",
        temporality=temporality,
        start_time_ns=start_time_ns,
        monotonic=True,
    )


def message_age(
    value: float,
    observed_at_ns: int,
    *,
    channel: str = "/robotics/runtime_probe",
    start_time_ns: int = 0,
) -> HistogramSample:
    bounds = (1.0, 5.0, 10.0, 20.0, 50.0, 100.0)
    bucket_index = next(
        (index for index, boundary in enumerate(bounds) if value <= boundary),
        len(bounds),
    )
    bucket_counts = [0] * (len(bounds) + 1)
    bucket_counts[bucket_index] = 1
    return HistogramSample(
        name="robotics.message.age",
        unit="ms",
        observed_at_ns=observed_at_ns,
        count=1,
        bucket_counts=tuple(bucket_counts),
        explicit_bounds=bounds,
        attributes={"domain.id": "camera", "channel": channel},
        temporality="delta",
        start_time_ns=start_time_ns,
        min=value,
        max=value,
        sum=value,
    )


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
    policy = data_plane_policy(shm_transport=True)
    runtime = {
        "data_plane": {
            "shm_transport": True,
            "data_sharing": False,
            "private_ipc": False,
        }
    }
    samples = [
        message_age(20, 2),
        counter("robotics.message.received", 100, 2),
        counter("robotics.message.lost", 0, 2),
        counter("robotics.message.sequence_error", 0, 2),
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


def test_data_plane_loss_is_derived_from_delta_counters() -> None:
    policy = data_plane_policy(max_loss_ratio=0.1)
    runtime = {"data_plane": dict(policy)}
    samples = [
        message_age(5, 2),
        counter("robotics.message.received", 40, 1),
        counter("robotics.message.received", 50, 2, start_time_ns=1),
        counter("robotics.message.lost", 4, 1),
        counter("robotics.message.lost", 6, 2, start_time_ns=1),
        counter("robotics.message.sequence_error", 0, 1),
        counter("robotics.message.sequence_error", 0, 2, start_time_ns=1),
    ]

    evaluations = evaluate_data_plane_policy(
        policy,
        runtime,
        samples,
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=2,
    )

    loss = next(item for item in evaluations if item.assertion_id == "data-plane-loss-ratio")
    assert loss.status == "passed"
    assert loss.observed_value == 0.1


def test_data_plane_rejects_overlapping_or_misaligned_counter_intervals() -> None:
    policy = data_plane_policy(max_loss_ratio=0.1)
    runtime = {"data_plane": dict(policy)}
    common = [
        message_age(5, 2),
        counter("robotics.message.lost", 1, 2, start_time_ns=0),
        counter("robotics.message.sequence_error", 0, 1, start_time_ns=0),
        counter("robotics.message.sequence_error", 0, 2, start_time_ns=1),
    ]
    overlapping = evaluate_data_plane_policy(
        policy,
        runtime,
        [
            *common,
            counter("robotics.message.received", 50, 1, start_time_ns=0),
            counter("robotics.message.received", 50, 2, start_time_ns=0),
        ],
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=2,
    )
    misaligned = evaluate_data_plane_policy(
        policy,
        runtime,
        [
            message_age(5, 2),
            counter("robotics.message.received", 50, 1, start_time_ns=0),
            counter("robotics.message.received", 50, 2, start_time_ns=1),
            counter("robotics.message.lost", 1, 2, start_time_ns=0),
            counter("robotics.message.sequence_error", 0, 1, start_time_ns=0),
            counter("robotics.message.sequence_error", 0, 2, start_time_ns=1),
        ],
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=2,
    )

    overlap_loss = next(
        item for item in overlapping if item.assertion_id == "data-plane-loss-ratio"
    )
    misaligned_loss = next(
        item for item in misaligned if item.assertion_id == "data-plane-loss-ratio"
    )
    assert overlap_loss.status == "error"
    assert "overlapping delta intervals" in overlap_loss.message
    assert misaligned_loss.status == "error"
    assert "same collection intervals" in misaligned_loss.message


def test_data_plane_rejects_a_short_sample_inside_a_long_measurement_window() -> None:
    policy = data_plane_policy()
    runtime = {"data_plane": dict(policy)}
    start_ns = 20_000_000_000
    end_ns = 21_000_000_000
    samples = [
        message_age(5, end_ns, start_time_ns=start_ns),
        counter(
            "robotics.message.received",
            50,
            end_ns,
            start_time_ns=start_ns,
        ),
        counter(
            "robotics.message.lost",
            0,
            end_ns,
            start_time_ns=start_ns,
        ),
        counter(
            "robotics.message.sequence_error",
            0,
            end_ns,
            start_time_ns=start_ns,
        ),
    ]

    evaluations = evaluate_data_plane_policy(
        policy,
        runtime,
        samples,
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=60_000_000_000,
    )

    dynamic = [
        item
        for item in evaluations
        if item.assertion_id.startswith("data-plane-message")
        or item.assertion_id.startswith("data-plane-loss")
        or item.assertion_id.startswith("data-plane-sequence")
    ]
    assert dynamic
    assert all(item.status == "error" for item in dynamic)
    assert any("coverage tolerance" in item.message for item in dynamic)


def test_data_plane_loss_uses_cumulative_counter_baselines() -> None:
    policy = data_plane_policy(max_loss_ratio=0.1)
    runtime = {"data_plane": dict(policy)}
    samples = [
        message_age(5, 3, start_time_ns=2),
        counter(
            "robotics.message.received",
            100,
            2,
            temporality="cumulative",
            start_time_ns=0,
        ),
        counter(
            "robotics.message.received",
            190,
            3,
            temporality="cumulative",
            start_time_ns=0,
        ),
        counter(
            "robotics.message.lost",
            10,
            2,
            temporality="cumulative",
            start_time_ns=0,
        ),
        counter(
            "robotics.message.lost",
            20,
            3,
            temporality="cumulative",
            start_time_ns=0,
        ),
        counter(
            "robotics.message.sequence_error",
            0,
            2,
            temporality="cumulative",
            start_time_ns=0,
        ),
        counter(
            "robotics.message.sequence_error",
            0,
            3,
            temporality="cumulative",
            start_time_ns=0,
        ),
    ]

    evaluations = evaluate_data_plane_policy(
        policy,
        runtime,
        samples,
        domain_id="camera",
        window_start_ns=2,
        window_end_ns=3,
    )

    loss = next(item for item in evaluations if item.assertion_id == "data-plane-loss-ratio")
    assert loss.status == "passed"
    assert loss.observed_value == 0.1


def test_data_plane_cumulative_counters_survive_process_reset() -> None:
    policy = data_plane_policy(max_loss_ratio=0.1)
    runtime = {"data_plane": dict(policy)}
    samples = [
        message_age(5, 5),
        counter(
            "robotics.message.received",
            100,
            2,
            temporality="cumulative",
            start_time_ns=0,
        ),
        counter(
            "robotics.message.received",
            90,
            5,
            temporality="cumulative",
            start_time_ns=2,
        ),
        counter(
            "robotics.message.lost",
            10,
            2,
            temporality="cumulative",
            start_time_ns=0,
        ),
        counter(
            "robotics.message.lost",
            10,
            5,
            temporality="cumulative",
            start_time_ns=2,
        ),
        counter(
            "robotics.message.sequence_error",
            0,
            2,
            temporality="cumulative",
            start_time_ns=0,
        ),
        counter(
            "robotics.message.sequence_error",
            0,
            5,
            temporality="cumulative",
            start_time_ns=2,
        ),
    ]

    evaluations = evaluate_data_plane_policy(
        policy,
        runtime,
        samples,
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=5,
    )

    loss = next(item for item in evaluations if item.assertion_id == "data-plane-loss-ratio")
    assert loss.status == "passed"
    assert loss.observed_value == 20 / 210


def test_data_plane_rejects_last_value_ratio_and_empty_counters() -> None:
    policy = data_plane_policy()
    runtime = {"data_plane": dict(policy)}
    common = [
        message_age(5, 1),
        MetricSample(
            "robotics.message.loss_ratio",
            0,
            "1",
            1,
            {"domain.id": "camera", "channel": "/robotics/runtime_probe"},
        ),
    ]

    last_value = evaluate_data_plane_policy(
        policy,
        runtime,
        common,
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=1,
    )
    empty = evaluate_data_plane_policy(
        policy,
        runtime,
        [
            *common,
            counter("robotics.message.received", 0, 1),
            counter("robotics.message.lost", 0, 1),
            counter("robotics.message.sequence_error", 0, 1),
        ],
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=1,
    )

    last_value_loss = next(
        item for item in last_value if item.assertion_id == "data-plane-loss-ratio"
    )
    empty_loss = next(item for item in empty if item.assertion_id == "data-plane-loss-ratio")
    assert last_value_loss.status == "error"
    assert "robotics.message.received" in last_value_loss.message
    assert empty_loss.status == "error"
    assert "no observations" in empty_loss.message


def test_data_plane_rejects_ambiguous_channels_and_wrong_counter_units() -> None:
    policy = data_plane_policy()
    runtime = {"data_plane": dict(policy)}
    base = [
        message_age(5, 1),
        counter("robotics.message.received", 10, 1),
        counter("robotics.message.lost", 0, 1),
        counter("robotics.message.sequence_error", 0, 1),
    ]
    ambiguous = evaluate_data_plane_policy(
        policy,
        runtime,
        [
            *base,
            message_age(6, 1, channel="/camera/image"),
        ],
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=1,
    )
    wrong_unit = evaluate_data_plane_policy(
        policy,
        runtime,
        [
            base[0],
            counter("robotics.message.received", 10, 1, unit="1"),
            counter("robotics.message.lost", 0, 1, unit="1"),
            counter("robotics.message.sequence_error", 0, 1),
        ],
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=1,
    )

    assert {
        item.status
        for item in ambiguous
        if item.assertion_id in {"data-plane-message-age", "data-plane-loss-ratio"}
    } == {"error"}
    wrong_loss = next(item for item in wrong_unit if item.assertion_id == "data-plane-loss-ratio")
    assert wrong_loss.status == "error"
    assert "requires unit {message}" in wrong_loss.message


def test_data_plane_rejects_message_age_gauge() -> None:
    policy = data_plane_policy()
    runtime = {"data_plane": dict(policy)}
    evaluations = evaluate_data_plane_policy(
        policy,
        runtime,
        [
            MetricSample(
                "robotics.message.age",
                5,
                "ms",
                1,
                {
                    "domain.id": "camera",
                    "channel": "/robotics/runtime_probe",
                },
            ),
            counter("robotics.message.received", 10, 1),
            counter("robotics.message.lost", 0, 1),
            counter("robotics.message.sequence_error", 0, 1),
        ],
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=1,
    )

    age = next(item for item in evaluations if item.assertion_id == "data-plane-message-age")
    loss = next(item for item in evaluations if item.assertion_id == "data-plane-loss-ratio")
    assert age.status == "error"
    assert loss.status == "error"
    assert "must be an OTLP Histogram" in age.message


def test_data_plane_sequence_integrity_fails_on_invalid_metadata() -> None:
    policy = data_plane_policy()
    runtime = {"data_plane": dict(policy)}

    evaluations = evaluate_data_plane_policy(
        policy,
        runtime,
        [
            message_age(5, 1),
            counter("robotics.message.received", 9, 1),
            counter("robotics.message.lost", 0, 1),
            counter("robotics.message.sequence_error", 1, 1),
        ],
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=1,
    )

    integrity = next(
        item for item in evaluations if item.assertion_id == "data-plane-sequence-integrity"
    )
    assert integrity.status == "failed"
    assert integrity.observed_value == 1


def test_data_plane_rejects_an_unqualified_sequence_measurement_method() -> None:
    policy = data_plane_policy()
    runtime = {"data_plane": dict(policy)}

    evaluations = evaluate_data_plane_policy(
        policy,
        runtime,
        [
            message_age(5, 1),
            counter("robotics.message.received", 9, 1, sequence_method="payload_counter"),
            counter("robotics.message.lost", 0, 1, sequence_method="payload_counter"),
            counter(
                "robotics.message.sequence_error",
                0,
                1,
                sequence_method="payload_counter",
            ),
        ],
        domain_id="camera",
        window_start_ns=0,
        window_end_ns=1,
    )

    loss = next(item for item in evaluations if item.assertion_id == "data-plane-loss-ratio")
    assert loss.status == "error"
    assert "robotics.message.received" in loss.message

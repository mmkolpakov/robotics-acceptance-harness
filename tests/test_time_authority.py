from __future__ import annotations

from robotics_acceptance_harness.metrics import HistogramSample, MetricSample
from robotics_acceptance_harness.time_authority import (
    DELIVERY_LATENCY_METRIC,
    INDEPENDENT_CLOCK_OFFSET_METHOD,
    LEGACY_OFFSET_METRIC,
    METHOD_ATTRIBUTE,
    RMW_LATENCY_METHOD,
    evaluate_time_authority,
)

RUN_ID = "run-01234567-89ab-4def-8123-456789abcdef"
BOUNDS = (0.5, 1.0, 2.0, 5.0)


def policy() -> dict[str, float | int]:
    return {
        "time_authority_min_samples": 30,
        "max_time_authority_delivery_latency_p50_ms": 1,
        "max_time_authority_delivery_latency_p95_ms": 2,
        "max_time_authority_delivery_latency_ms": 5,
    }


def histogram_sample(value: float, observed_at_ns: int) -> HistogramSample:
    bucket_index = next(
        (index for index, boundary in enumerate(BOUNDS) if value <= boundary),
        len(BOUNDS),
    )
    bucket_counts = [0] * (len(BOUNDS) + 1)
    bucket_counts[bucket_index] = 1
    return HistogramSample(
        name=DELIVERY_LATENCY_METRIC,
        unit="ms",
        observed_at_ns=observed_at_ns,
        count=1,
        bucket_counts=tuple(bucket_counts),
        explicit_bounds=BOUNDS,
        attributes={
            "run.id": RUN_ID,
            "domain.id": "camera-domain",
            "time.source.id": "simulation-clock",
            METHOD_ATTRIBUTE: RMW_LATENCY_METHOD,
        },
        temporality="delta",
        start_time_ns=observed_at_ns - 1,
        min=value,
        max=value,
        sum=value,
    )


def samples(count: int) -> list[HistogramSample]:
    return [histogram_sample(index / 20, index + 2) for index in range(count)]


def test_time_authority_uses_attributed_measurement_window() -> None:
    observation = evaluate_time_authority(
        policy(),
        samples(30),
        run_id=RUN_ID,
        domain_id="camera-domain",
        source_id="simulation-clock",
        window_start_ns=1,
        window_end_ns=31,
    )

    assert observation.sample_count == 30
    assert observation.within_policy
    assert observation.measurement_kind == "delivery_latency"
    assert observation.p50_ms < observation.p95_ms


def test_time_authority_fails_when_sample_count_is_short() -> None:
    observation = evaluate_time_authority(
        policy(),
        samples(29),
        run_id=RUN_ID,
        domain_id="camera-domain",
        source_id="simulation-clock",
        window_start_ns=1,
        window_end_ns=31,
    )

    assert observation.sample_count == 29
    assert not observation.within_policy


def test_time_authority_rejects_legacy_gauge_but_allows_stable_histogram() -> None:
    legacy = [
        MetricSample(
            DELIVERY_LATENCY_METRIC,
            0,
            "ms",
            index + 1,
            {
                "run.id": RUN_ID,
                "domain.id": "camera-domain",
                "time.source.id": "simulation-clock",
                METHOD_ATTRIBUTE: RMW_LATENCY_METHOD,
            },
        )
        for index in range(30)
    ]
    stable = [histogram_sample(0.5, index + 2) for index in range(30)]

    legacy_observation = evaluate_time_authority(
        policy(),
        legacy,
        run_id=RUN_ID,
        domain_id="camera-domain",
        source_id="simulation-clock",
        window_start_ns=1,
        window_end_ns=31,
    )
    stable_observation = evaluate_time_authority(
        policy(),
        stable,
        run_id=RUN_ID,
        domain_id="camera-domain",
        source_id="simulation-clock",
        window_start_ns=1,
        window_end_ns=31,
    )

    assert legacy_observation.sample_count == 0
    assert not legacy_observation.within_policy
    assert stable_observation.sample_count == 30
    assert stable_observation.within_policy


def test_time_authority_counts_histogram_events() -> None:
    observation = evaluate_time_authority(
        policy(),
        [
            HistogramSample(
                name=DELIVERY_LATENCY_METRIC,
                unit="ms",
                observed_at_ns=30,
                count=30,
                bucket_counts=(10, 15, 5, 0),
                explicit_bounds=(0.5, 1, 2),
                attributes={
                    "run.id": RUN_ID,
                    "domain.id": "camera-domain",
                    "time.source.id": "simulation-clock",
                    METHOD_ATTRIBUTE: RMW_LATENCY_METHOD,
                },
                temporality="delta",
                start_time_ns=1,
                min=0.1,
                max=1.9,
                sum=24,
            )
        ],
        run_id=RUN_ID,
        domain_id="camera-domain",
        source_id="simulation-clock",
        window_start_ns=1,
        window_end_ns=30,
    )

    assert observation.sample_count == 30
    assert observation.p50_ms == 1
    assert observation.p95_ms == 1.9
    assert observation.within_policy


def test_legacy_policy_requires_independent_clock_offset_measurements() -> None:
    legacy_policy = {
        "time_authority_min_samples": 3,
        "max_clock_offset_p50_ms": 1,
        "max_clock_offset_p95_ms": 2,
        "max_clock_offset_ms": 5,
    }
    attributes = {
        "run.id": RUN_ID,
        "domain.id": "camera-domain",
        "time.source.id": "simulation-clock",
        METHOD_ATTRIBUTE: INDEPENDENT_CLOCK_OFFSET_METHOD,
    }
    offset_samples = [
        MetricSample(
            LEGACY_OFFSET_METRIC,
            value,
            "ms",
            index,
            attributes,
        )
        for index, value in enumerate((-0.5, 1.0, -1.5), start=1)
    ]

    observation = evaluate_time_authority(
        legacy_policy,
        offset_samples,
        run_id=RUN_ID,
        domain_id="camera-domain",
        source_id="simulation-clock",
        window_start_ns=1,
        window_end_ns=3,
    )

    assert observation.measurement_kind == "clock_offset"
    assert observation.sample_count == 3
    assert observation.p50_ms == 1
    assert observation.max_ms == 1.5
    assert observation.within_policy


def test_legacy_policy_rejects_rmw_latency_as_clock_offset() -> None:
    legacy_policy = {
        "time_authority_min_samples": 1,
        "max_clock_offset_p50_ms": 1,
        "max_clock_offset_p95_ms": 2,
        "max_clock_offset_ms": 5,
    }
    sample = MetricSample(
        LEGACY_OFFSET_METRIC,
        0.1,
        "ms",
        1,
        {
            "run.id": RUN_ID,
            "domain.id": "camera-domain",
            "time.source.id": "simulation-clock",
            METHOD_ATTRIBUTE: RMW_LATENCY_METHOD,
        },
    )

    observation = evaluate_time_authority(
        legacy_policy,
        [sample],
        run_id=RUN_ID,
        domain_id="camera-domain",
        source_id="simulation-clock",
        window_start_ns=1,
        window_end_ns=1,
    )

    assert observation.sample_count == 0
    assert not observation.within_policy

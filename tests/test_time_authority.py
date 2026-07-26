from __future__ import annotations

from robotics_acceptance_harness.metrics import MetricSample
from robotics_acceptance_harness.time_authority import (
    OFFSET_METRIC,
    evaluate_time_authority,
)

RUN_ID = "run-01234567-89ab-4def-8123-456789abcdef"


def policy() -> dict[str, float | int]:
    return {
        "time_authority_min_samples": 30,
        "max_clock_offset_p50_ms": 1,
        "max_clock_offset_p95_ms": 2,
        "max_clock_offset_ms": 5,
    }


def samples(count: int) -> list[MetricSample]:
    return [
        MetricSample(
            OFFSET_METRIC,
            index / 20,
            "ms",
            index + 1,
            {
                "run.id": RUN_ID,
                "domain.id": "camera-domain",
                "time.source.id": "simulation-clock",
            },
        )
        for index in range(count)
    ]


def test_time_authority_uses_attributed_measurement_window() -> None:
    observation = evaluate_time_authority(
        policy(),
        samples(30),
        run_id=RUN_ID,
        domain_id="camera-domain",
        source_id="simulation-clock",
        window_start_ns=1,
        window_end_ns=30,
    )

    assert observation.sample_count == 30
    assert observation.within_policy
    assert observation.p50_offset_ms < observation.p95_offset_ms


def test_time_authority_fails_when_sample_count_is_short() -> None:
    observation = evaluate_time_authority(
        policy(),
        samples(29),
        run_id=RUN_ID,
        domain_id="camera-domain",
        source_id="simulation-clock",
        window_start_ns=1,
        window_end_ns=30,
    )

    assert observation.sample_count == 29
    assert not observation.within_policy

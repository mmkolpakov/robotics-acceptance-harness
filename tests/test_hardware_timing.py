from __future__ import annotations

import pytest

from robotics_acceptance_harness.hardware_timing import (
    AGE_METRIC,
    DRIFT_METRIC,
    MONOTONIC_METRIC,
    OFFSET_METRIC,
    PROTOCOL_ATTRIBUTE,
    SOURCE_ATTRIBUTE,
    HardwareTimingInputError,
    evaluate_hardware_timing,
)
from robotics_acceptance_harness.metrics import MetricSample

POLICY = {
    "clock_sync_protocol": "ptp",
    "max_clock_offset_ms": 5,
    "max_clock_drift_ppm": 20,
    "max_message_age_ms": 50,
}
ATTRIBUTES = {
    PROTOCOL_ATTRIBUTE: "ptp",
    SOURCE_ATTRIBUTE: "pmc",
}


def samples(*, offset: float = 1, drift: float = 2, age: float = 3) -> list[MetricSample]:
    result: list[MetricSample] = []
    for timestamp, adjustment in ((1_000_000_000, 0.0), (2_000_000_000, 0.5)):
        result.extend(
            (
                MetricSample(OFFSET_METRIC, offset + adjustment, "ms", timestamp, ATTRIBUTES),
                MetricSample(DRIFT_METRIC, drift, "ppm", timestamp, ATTRIBUTES),
                MetricSample(AGE_METRIC, age, "ms", timestamp, ATTRIBUTES),
                MetricSample(MONOTONIC_METRIC, 1, "1", timestamp, ATTRIBUTES),
            )
        )
    return result


def test_evaluates_aligned_hardware_timing_metrics() -> None:
    observation = evaluate_hardware_timing(POLICY, samples())

    assert observation.sync_protocol == "ptp"
    assert observation.source == "pmc"
    assert observation.sample_count == 2
    assert observation.offset_ms == 1.5
    assert observation.jitter_ms == 0.25
    assert observation.drift_ppm == 2
    assert observation.max_sample_age_ms == 3
    assert observation.monotonic
    assert observation.within_policy


def test_out_of_policy_measurement_is_a_failed_observation_not_bad_input() -> None:
    observation = evaluate_hardware_timing(POLICY, samples(offset=10))

    assert not observation.within_policy


def test_rejects_missing_or_misaligned_measurements() -> None:
    with pytest.raises(HardwareTimingInputError, match="missing hardware timing metrics"):
        evaluate_hardware_timing(POLICY, samples()[:3])

    unaligned = samples()
    unaligned[-1] = MetricSample(
        MONOTONIC_METRIC,
        1,
        "1",
        3_000_000_000,
        ATTRIBUTES,
    )
    with pytest.raises(HardwareTimingInputError, match="unaligned hardware timing point"):
        evaluate_hardware_timing(POLICY, unaligned)


def test_rejects_wrong_units_metadata_and_protocol() -> None:
    wrong_unit = samples()
    wrong_unit[0] = MetricSample(OFFSET_METRIC, 1, "s", 1_000_000_000, ATTRIBUTES)
    with pytest.raises(HardwareTimingInputError, match="requires unit ms"):
        evaluate_hardware_timing(POLICY, wrong_unit)

    wrong_protocol = samples()
    wrong_protocol[0] = MetricSample(
        OFFSET_METRIC,
        1,
        "ms",
        1_000_000_000,
        {**ATTRIBUTES, PROTOCOL_ATTRIBUTE: "chrony_ntp"},
    )
    with pytest.raises(HardwareTimingInputError, match="metadata changed"):
        evaluate_hardware_timing(POLICY, wrong_protocol)

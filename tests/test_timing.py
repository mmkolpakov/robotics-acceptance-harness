from __future__ import annotations

import pytest

from robotics_acceptance_harness.timing import (
    ClockSample,
    TimingValidationError,
    evaluate_timing,
)


def test_realtime_timing_passes_at_policy_boundary() -> None:
    samples = [
        ClockSample(0, 0, real_time_factor=0.95, deadline_miss_ratio=0.01),
        ClockSample(1_000_000_000, 950_000_000, real_time_factor=0.96, deadline_miss_ratio=0),
    ]
    result = evaluate_timing(
        {"time_mode": "simulation_realtime"},
        {"min_realtime_factor": 0.95, "max_deadline_miss_ratio": 0.01},
        samples,
    )
    assert result.real_time_factor == 0.95
    assert result.deadline_miss_ratio == 0.01


def test_backwards_clock_is_rejected_in_every_mode() -> None:
    samples = [ClockSample(0, 10), ClockSample(1, 9)]
    with pytest.raises(TimingValidationError, match="moved backwards"):
        evaluate_timing(
            {"time_mode": "simulation_stepped"},
            {"step_size_sec": 0.001},
            samples,
        )


def test_realtime_policy_rejects_slow_or_late_execution() -> None:
    samples = [
        ClockSample(0, 0, real_time_factor=0.7, deadline_miss_ratio=0.1),
        ClockSample(1, 1, real_time_factor=0.8, deadline_miss_ratio=0.2),
    ]
    with pytest.raises(TimingValidationError) as caught:
        evaluate_timing(
            {"time_mode": "simulation_realtime"},
            {"min_realtime_factor": 0.95, "max_deadline_miss_ratio": 0.01},
            samples,
        )
    paths = {issue.json_path for issue in caught.value.issues}
    assert "$.time_policy.min_realtime_factor" in paths
    assert "$.time_policy.max_deadline_miss_ratio" in paths


def test_playback_requires_clock_progress_and_frequency() -> None:
    samples = [ClockSample(0, 0), ClockSample(2_000_000_000, 1_000_000_000)]
    with pytest.raises(TimingValidationError) as caught:
        evaluate_timing(
            {"time_mode": "playback_clocked"},
            {"min_clock_hz": 1.0},
            samples,
        )
    assert caught.value.issues[0].json_path == "$.time_policy.min_clock_hz"


def test_hardware_time_checks_offset_drift_and_message_age() -> None:
    samples = [
        ClockSample(0, 0, offset_ms=6, drift_ppm=5, message_age_ms=20),
        ClockSample(1, 1, offset_ms=4, drift_ppm=30, message_age_ms=60),
    ]
    with pytest.raises(TimingValidationError) as caught:
        evaluate_timing(
            {"time_mode": "hardware_realtime"},
            {
                "max_clock_offset_ms": 5,
                "max_clock_drift_ppm": 20,
                "max_message_age_ms": 50,
            },
            samples,
        )
    assert len(caught.value.issues) == 3

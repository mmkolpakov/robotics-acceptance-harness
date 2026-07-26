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


def test_stepped_timing_accepts_declared_multiples() -> None:
    samples = [
        ClockSample(0, 0),
        ClockSample(1_000_000, 1_000_000),
        ClockSample(2_000_000, 2_000_000),
    ]

    result = evaluate_timing(
        {"time_mode": "simulation_stepped"},
        {"step_size_sec": 0.001, "max_skipped_steps": 0},
        samples,
    )

    assert result.monotonic


def test_stepped_timing_rejects_large_jump() -> None:
    samples = [
        ClockSample(0, 0),
        ClockSample(1_000_000, 999_000_000_000),
    ]

    with pytest.raises(TimingValidationError) as caught:
        evaluate_timing(
            {"time_mode": "simulation_stepped"},
            {"step_size_sec": 0.001, "max_skipped_steps": 0},
            samples,
        )

    assert caught.value.observation.monotonic
    assert any(
        issue.json_path == "$.time_policy.max_skipped_steps" for issue in caught.value.issues
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

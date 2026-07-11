from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from robotics_acceptance_harness.readiness import ReadinessIssue


class TimingValidationError(ValueError):
    """Raised when observed clock behavior violates the selected time policy."""

    def __init__(self, issues: tuple[ReadinessIssue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{issue.json_path}: {issue.message}" for issue in issues))


@dataclass(frozen=True, slots=True)
class ClockSample:
    observed_at_ns: int
    source_time_ns: int
    real_time_factor: float | None = None
    deadline_miss_ratio: float | None = None
    offset_ms: float | None = None
    drift_ppm: float | None = None
    message_age_ms: float | None = None


@dataclass(frozen=True, slots=True)
class TimingObservation:
    monotonic: bool
    offset_ms: float
    drift_ppm: float
    real_time_factor: float
    deadline_miss_ratio: float
    max_message_age_ms: float
    clock_hz: float


def _required_values(
    samples: Sequence[ClockSample],
    attribute: str,
    path: str,
    issues: list[ReadinessIssue],
) -> list[float]:
    values = [getattr(sample, attribute) for sample in samples]
    if any(value is None for value in values):
        issues.append(ReadinessIssue(path, f"{attribute} was not observed for every sample"))
        return []
    return [float(value) for value in values if value is not None]


def evaluate_timing(
    execution: Mapping[str, Any],
    time_policy: Mapping[str, Any],
    samples: Sequence[ClockSample],
) -> TimingObservation:
    """Evaluate clock monotonicity and mode-specific timing limits."""

    if not samples:
        raise TimingValidationError((ReadinessIssue("$.time_policy", "no clock samples"),))

    issues: list[ReadinessIssue] = []
    monotonic = all(
        current.source_time_ns >= previous.source_time_ns
        for previous, current in zip(samples, samples[1:], strict=False)
    )
    if not monotonic:
        issues.append(ReadinessIssue("$.time_policy", "source clock moved backwards"))

    elapsed_ns = samples[-1].observed_at_ns - samples[0].observed_at_ns
    clock_hz = (len(samples) - 1) * 1_000_000_000 / elapsed_ns if elapsed_ns > 0 else 0.0
    mode = execution["time_mode"]

    real_time_factor = 0.0
    deadline_miss_ratio = 0.0
    offset_ms = 0.0
    drift_ppm = 0.0
    max_message_age_ms = 0.0

    if mode == "simulation_realtime":
        rtf_values = _required_values(
            samples,
            "real_time_factor",
            "$.time_policy.min_realtime_factor",
            issues,
        )
        deadline_values = _required_values(
            samples,
            "deadline_miss_ratio",
            "$.time_policy.max_deadline_miss_ratio",
            issues,
        )
        if rtf_values:
            real_time_factor = min(rtf_values)
            if real_time_factor < time_policy["min_realtime_factor"]:
                issues.append(
                    ReadinessIssue(
                        "$.time_policy.min_realtime_factor",
                        f"minimum observed value was {real_time_factor}",
                    )
                )
        if deadline_values:
            deadline_miss_ratio = max(deadline_values)
            if deadline_miss_ratio > time_policy["max_deadline_miss_ratio"]:
                issues.append(
                    ReadinessIssue(
                        "$.time_policy.max_deadline_miss_ratio",
                        f"maximum observed value was {deadline_miss_ratio}",
                    )
                )
    elif mode == "playback_clocked":
        if clock_hz < time_policy["min_clock_hz"]:
            issues.append(
                ReadinessIssue(
                    "$.time_policy.min_clock_hz",
                    f"observed clock frequency was {clock_hz}",
                )
            )
        if samples[-1].source_time_ns <= samples[0].source_time_ns:
            issues.append(ReadinessIssue("$.time_policy", "playback clock did not advance"))
    elif mode == "hardware_realtime":
        offset_values = _required_values(
            samples,
            "offset_ms",
            "$.time_policy.max_clock_offset_ms",
            issues,
        )
        drift_values = _required_values(
            samples,
            "drift_ppm",
            "$.time_policy.max_clock_drift_ppm",
            issues,
        )
        age_values = _required_values(
            samples,
            "message_age_ms",
            "$.time_policy.max_message_age_ms",
            issues,
        )
        if offset_values:
            offset_ms = max(abs(value) for value in offset_values)
            if offset_ms > time_policy["max_clock_offset_ms"]:
                issues.append(
                    ReadinessIssue(
                        "$.time_policy.max_clock_offset_ms",
                        f"maximum absolute offset was {offset_ms}",
                    )
                )
        if drift_values:
            drift_ppm = max(abs(value) for value in drift_values)
            if drift_ppm > time_policy["max_clock_drift_ppm"]:
                issues.append(
                    ReadinessIssue(
                        "$.time_policy.max_clock_drift_ppm",
                        f"maximum absolute drift was {drift_ppm}",
                    )
                )
        if age_values:
            max_message_age_ms = max(age_values)
            if max_message_age_ms > time_policy["max_message_age_ms"]:
                issues.append(
                    ReadinessIssue(
                        "$.time_policy.max_message_age_ms",
                        f"maximum message age was {max_message_age_ms}",
                    )
                )

    if issues:
        raise TimingValidationError(tuple(issues))
    return TimingObservation(
        monotonic=monotonic,
        offset_ms=offset_ms,
        drift_ppm=drift_ppm,
        real_time_factor=real_time_factor,
        deadline_miss_ratio=deadline_miss_ratio,
        max_message_age_ms=max_message_age_ms,
        clock_hz=clock_hz,
    )


__all__ = [
    "ClockSample",
    "TimingObservation",
    "TimingValidationError",
    "evaluate_timing",
]

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from robotics_acceptance_harness.metrics import MetricSample, percentile

OFFSET_METRIC = "robotics.time_authority.offset"
RUN_ATTRIBUTE = "run.id"
DOMAIN_ATTRIBUTE = "domain.id"
SOURCE_ATTRIBUTE = "time.source.id"


@dataclass(frozen=True, slots=True)
class TimeAuthorityObservation:
    source_id: str
    sample_count: int
    window_start_ns: int
    window_end_ns: int
    p50_offset_ms: float
    p95_offset_ms: float
    max_offset_ms: float
    within_policy: bool


def evaluate_time_authority(
    time_policy: Mapping[str, Any],
    samples: Sequence[MetricSample],
    *,
    run_id: str,
    domain_id: str,
    source_id: str,
    window_start_ns: int,
    window_end_ns: int,
) -> TimeAuthorityObservation:
    """Evaluate measured offsets to the run's declared time authority."""

    selected = [
        sample
        for sample in samples
        if sample.name == OFFSET_METRIC
        and sample.unit == "ms"
        and window_start_ns <= sample.observed_at_ns <= window_end_ns
        and sample.attributes.get(RUN_ATTRIBUTE) == run_id
        and sample.attributes.get(DOMAIN_ATTRIBUTE) == domain_id
        and sample.attributes.get(SOURCE_ATTRIBUTE) == source_id
    ]
    offsets = [abs(sample.value) for sample in selected]
    p50 = percentile(offsets, 0.50) if offsets else 0.0
    p95 = percentile(offsets, 0.95) if offsets else 0.0
    maximum = max(offsets, default=0.0)
    within_policy = (
        len(selected) >= int(time_policy["time_authority_min_samples"])
        and p50 <= float(time_policy["max_clock_offset_p50_ms"])
        and p95 <= float(time_policy["max_clock_offset_p95_ms"])
        and maximum <= float(time_policy["max_clock_offset_ms"])
    )
    return TimeAuthorityObservation(
        source_id=source_id,
        sample_count=len(selected),
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
        p50_offset_ms=p50,
        p95_offset_ms=p95,
        max_offset_ms=maximum,
        within_policy=within_policy,
    )


__all__ = [
    "DOMAIN_ATTRIBUTE",
    "OFFSET_METRIC",
    "RUN_ATTRIBUTE",
    "SOURCE_ATTRIBUTE",
    "TimeAuthorityObservation",
    "evaluate_time_authority",
]

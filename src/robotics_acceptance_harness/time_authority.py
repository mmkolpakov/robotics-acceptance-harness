from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from robotics_acceptance_harness.metrics import (
    HistogramSample,
    MetricAggregationError,
    MetricPoint,
    MetricSample,
    aggregate_metric_points,
    histogram_window_coverage,
    percentile,
    require_window_coverage,
)

DELIVERY_LATENCY_METRIC = "robotics.time_authority.delivery_latency"
LEGACY_OFFSET_METRIC = "robotics.time_authority.offset"
RUN_ATTRIBUTE = "run.id"
DOMAIN_ATTRIBUTE = "domain.id"
SOURCE_ATTRIBUTE = "time.source.id"
METHOD_ATTRIBUTE = "time.measurement.method"
RMW_LATENCY_METHOD = "rmw_source_to_reception_latency"
INDEPENDENT_CLOCK_OFFSET_METHOD = "independent_clock_offset"
type TimeAuthorityMeasurementKind = Literal["clock_offset", "delivery_latency"]


@dataclass(frozen=True, slots=True)
class TimeAuthorityObservation:
    """A typed measurement of the declared ROS time authority."""

    source_id: str
    measurement_kind: TimeAuthorityMeasurementKind
    sample_count: int
    window_start_ns: int
    window_end_ns: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    within_policy: bool


def _matches_context(
    sample: MetricPoint,
    *,
    run_id: str,
    domain_id: str,
    source_id: str,
    window_start_ns: int,
    window_end_ns: int,
) -> bool:
    return (
        window_start_ns <= sample.observed_at_ns <= window_end_ns
        and sample.attributes.get(RUN_ATTRIBUTE) == run_id
        and sample.attributes.get(DOMAIN_ATTRIBUTE) == domain_id
        and sample.attributes.get(SOURCE_ATTRIBUTE) == source_id
    )


def _delivery_latency_observation(
    samples: Sequence[MetricPoint],
    *,
    run_id: str,
    domain_id: str,
    source_id: str,
    window_start_ns: int,
    window_end_ns: int,
) -> tuple[int, float, float, float, bool]:
    selected = [
        sample
        for sample in samples
        if isinstance(sample, HistogramSample)
        and sample.name == DELIVERY_LATENCY_METRIC
        and sample.unit == "ms"
        and sample.attributes.get(METHOD_ATTRIBUTE) == RMW_LATENCY_METHOD
        and _matches_context(
            sample,
            run_id=run_id,
            domain_id=domain_id,
            source_id=source_id,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
        )
    ]
    nonnegative = all(sample.min is not None and sample.min >= 0 for sample in selected)
    try:
        require_window_coverage(
            histogram_window_coverage(
                selected,
                window_start_ns=window_start_ns,
                window_end_ns=window_end_ns,
            ),
            metric_name=DELIVERY_LATENCY_METRIC,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
        )
        values = tuple(
            float(
                aggregate_metric_points(
                    selected,
                    aggregation,
                    window_start_ns=window_start_ns,
                    window_end_ns=window_end_ns,
                )
            )
            for aggregation in ("count", "p50", "p95", "max")
        )
    except MetricAggregationError:
        return 0, 0.0, 0.0, 0.0, False
    return int(values[0]), values[1], values[2], values[3], nonnegative


def _clock_offset_observation(
    samples: Sequence[MetricPoint],
    *,
    run_id: str,
    domain_id: str,
    source_id: str,
    window_start_ns: int,
    window_end_ns: int,
) -> tuple[int, float, float, float]:
    selected = [
        sample
        for sample in samples
        if isinstance(sample, MetricSample)
        and sample.instrument_kind == "gauge"
        and sample.name == LEGACY_OFFSET_METRIC
        and sample.unit == "ms"
        and sample.attributes.get(METHOD_ATTRIBUTE) == INDEPENDENT_CLOCK_OFFSET_METHOD
        and _matches_context(
            sample,
            run_id=run_id,
            domain_id=domain_id,
            source_id=source_id,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
        )
    ]
    offsets = [abs(sample.value) for sample in selected]
    if not offsets:
        return 0, 0.0, 0.0, 0.0
    return (
        len(offsets),
        percentile(offsets, 0.50),
        percentile(offsets, 0.95),
        max(offsets),
    )


def evaluate_time_authority(
    time_policy: Mapping[str, Any],
    samples: Sequence[MetricPoint],
    *,
    run_id: str,
    domain_id: str,
    source_id: str,
    window_start_ns: int,
    window_end_ns: int,
) -> TimeAuthorityObservation:
    """Evaluate the measurement kind explicitly declared by the scenario version."""

    canonical_policy = "max_time_authority_delivery_latency_ms" in time_policy
    if canonical_policy:
        sample_count, p50, p95, maximum, valid_values = _delivery_latency_observation(
            samples,
            run_id=run_id,
            domain_id=domain_id,
            source_id=source_id,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
        )
        measurement_kind: TimeAuthorityMeasurementKind = "delivery_latency"
        thresholds = (
            "max_time_authority_delivery_latency_p50_ms",
            "max_time_authority_delivery_latency_p95_ms",
            "max_time_authority_delivery_latency_ms",
        )
    else:
        sample_count, p50, p95, maximum = _clock_offset_observation(
            samples,
            run_id=run_id,
            domain_id=domain_id,
            source_id=source_id,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
        )
        measurement_kind = "clock_offset"
        valid_values = True
        thresholds = (
            "max_clock_offset_p50_ms",
            "max_clock_offset_p95_ms",
            "max_clock_offset_ms",
        )
    within_policy = (
        sample_count >= int(time_policy["time_authority_min_samples"])
        and valid_values
        and p50 <= float(time_policy[thresholds[0]])
        and p95 <= float(time_policy[thresholds[1]])
        and maximum <= float(time_policy[thresholds[2]])
    )
    return TimeAuthorityObservation(
        source_id=source_id,
        measurement_kind=measurement_kind,
        sample_count=sample_count,
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
        p50_ms=p50,
        p95_ms=p95,
        max_ms=maximum,
        within_policy=within_policy,
    )


__all__ = [
    "DOMAIN_ATTRIBUTE",
    "DELIVERY_LATENCY_METRIC",
    "INDEPENDENT_CLOCK_OFFSET_METHOD",
    "LEGACY_OFFSET_METRIC",
    "METHOD_ATTRIBUTE",
    "RMW_LATENCY_METHOD",
    "RUN_ATTRIBUTE",
    "SOURCE_ATTRIBUTE",
    "TimeAuthorityMeasurementKind",
    "TimeAuthorityObservation",
    "evaluate_time_authority",
]

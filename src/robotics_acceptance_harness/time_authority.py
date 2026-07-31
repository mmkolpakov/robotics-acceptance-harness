from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from robotics_acceptance_harness.metrics import (
    HistogramSample,
    MetricAggregationError,
    MetricPoint,
    aggregate_metric_points,
    histogram_window_coverage,
    require_window_coverage,
)

DELIVERY_LATENCY_METRIC = "robotics.time_authority.delivery_latency"
RUN_ATTRIBUTE = "run.id"
DOMAIN_ATTRIBUTE = "domain.id"
SOURCE_ATTRIBUTE = "time.source.id"
METHOD_ATTRIBUTE = "time.measurement.method"
RMW_LATENCY_METHOD = "rmw_source_to_reception_latency"


@dataclass(frozen=True, slots=True)
class TimeAuthorityObservation:
    """A typed measurement of the declared ROS time authority."""

    source_id: str
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
    """Evaluate canonical delivery-latency evidence for the declared time source."""

    sample_count, p50, p95, maximum, valid_values = _delivery_latency_observation(
        samples,
        run_id=run_id,
        domain_id=domain_id,
        source_id=source_id,
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
    )
    within_policy = (
        sample_count >= int(time_policy["time_authority_min_samples"])
        and valid_values
        and p50 <= float(time_policy["max_time_authority_delivery_latency_p50_ms"])
        and p95 <= float(time_policy["max_time_authority_delivery_latency_p95_ms"])
        and maximum <= float(time_policy["max_time_authority_delivery_latency_ms"])
    )
    return TimeAuthorityObservation(
        source_id=source_id,
        sample_count=sample_count,
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
        p50_ms=p50,
        p95_ms=p95,
        max_ms=maximum,
        within_policy=within_policy,
    )

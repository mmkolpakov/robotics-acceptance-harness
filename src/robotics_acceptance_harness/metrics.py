from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from statistics import fmean
from types import MappingProxyType
from typing import Any, Literal

MetricAttribute = str | bool | int | float
MetricTemporality = Literal["delta", "cumulative", "unspecified"]
type MetricSeriesKey = tuple[tuple[str, str, MetricAttribute], ...]
type MetricIntervalCoverage = tuple[tuple[MetricSeriesKey, int, int], ...]
METRIC_WINDOW_COVERAGE_TOLERANCE_NS = 1_000_000_000
METRIC_WINDOW_MAX_UNCOVERED_FRACTION = 0.05


@dataclass(frozen=True, slots=True)
class MetricSample:
    name: str
    value: float
    unit: str
    observed_at_ns: int
    attributes: Mapping[str, MetricAttribute] = field(default_factory=dict)
    instrument_kind: Literal["gauge", "sum"] = "gauge"
    temporality: MetricTemporality | None = None
    start_time_ns: int = 0
    monotonic: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))
        if not math.isfinite(self.value):
            raise ValueError("metric sample value must be finite")
        if self.instrument_kind not in {"gauge", "sum"}:
            raise ValueError("unsupported scalar metric instrument kind")
        if self.temporality not in {None, "delta", "cumulative", "unspecified"}:
            raise ValueError("unsupported metric aggregation temporality")
        if self.instrument_kind == "gauge" and self.temporality is not None:
            raise ValueError("gauge samples cannot declare aggregation temporality")
        if self.instrument_kind == "sum" and self.temporality is None:
            raise ValueError("sum samples require aggregation temporality")
        if self.start_time_ns < 0 or self.observed_at_ns < 0:
            raise ValueError("metric timestamps cannot be negative")
        if self.start_time_ns and self.start_time_ns > self.observed_at_ns:
            raise ValueError("metric start time cannot follow observation time")


@dataclass(frozen=True, slots=True)
class HistogramSample:
    name: str
    unit: str
    observed_at_ns: int
    count: int
    bucket_counts: tuple[int, ...]
    explicit_bounds: tuple[float, ...]
    attributes: Mapping[str, MetricAttribute] = field(default_factory=dict)
    temporality: MetricTemporality = "unspecified"
    start_time_ns: int = 0
    sum: float | None = None
    min: float | None = None
    max: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))
        if self.temporality not in {"delta", "cumulative", "unspecified"}:
            raise ValueError("unsupported histogram aggregation temporality")
        if self.start_time_ns < 0 or self.observed_at_ns < 0:
            raise ValueError("histogram timestamps cannot be negative")
        if self.start_time_ns and self.start_time_ns > self.observed_at_ns:
            raise ValueError("histogram start time cannot follow observation time")
        if self.count < 0 or any(count < 0 for count in self.bucket_counts):
            raise ValueError("histogram counts cannot be negative")
        if len(self.bucket_counts) != len(self.explicit_bounds) + 1:
            raise ValueError("histogram requires one more bucket count than explicit bounds")
        if sum(self.bucket_counts) != self.count:
            raise ValueError("histogram bucket counts must add up to count")
        if any(not math.isfinite(bound) for bound in self.explicit_bounds):
            raise ValueError("histogram explicit bounds must be finite")
        if any(
            current >= following
            for current, following in zip(
                self.explicit_bounds,
                self.explicit_bounds[1:],
                strict=False,
            )
        ):
            raise ValueError("histogram explicit bounds must be strictly increasing")
        if any(
            value is not None and not math.isfinite(value)
            for value in (self.sum, self.min, self.max)
        ):
            raise ValueError("histogram summary values must be finite")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("histogram min cannot exceed max")


type MetricPoint = MetricSample | HistogramSample


class MetricAggregationError(ValueError):
    """Raised when metric points cannot form an unambiguous window aggregate."""


@dataclass(frozen=True, slots=True)
class CounterWindowAggregate:
    total: float
    coverage: MetricIntervalCoverage


@dataclass(frozen=True, slots=True)
class AssertionEvaluation:
    assertion_id: str
    status: Literal["passed", "failed", "error"]
    observed_value: float | int | None
    unit: str
    message: str = ""


def percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _aggregate(name: str, values: Sequence[float]) -> float | int:
    if name == "min":
        return min(values)
    if name == "max":
        return max(values)
    if name == "mean":
        return fmean(values)
    if name == "p50":
        return percentile(values, 0.50)
    if name == "p95":
        return percentile(values, 0.95)
    if name == "p99":
        return percentile(values, 0.99)
    if name == "count":
        return len(values)
    raise ValueError(f"unsupported aggregation: {name}")


def _series_key(
    attributes: Mapping[str, MetricAttribute],
) -> MetricSeriesKey:
    return tuple(sorted((key, type(value).__name__, value) for key, value in attributes.items()))


def _validated_delta_points(
    samples: Sequence[MetricPoint],
    *,
    window_start_ns: int,
    window_end_ns: int,
    metric_name: str,
) -> list[MetricPoint]:
    selected = [
        sample
        for sample in samples
        if window_start_ns <= sample.observed_at_ns <= window_end_ns
        and sample.start_time_ns >= window_start_ns
    ]
    grouped: dict[MetricSeriesKey, list[MetricPoint]] = defaultdict(list)
    for sample in selected:
        if sample.start_time_ns >= sample.observed_at_ns:
            raise MetricAggregationError(
                f"{metric_name} contains an empty or reversed delta interval"
            )
        grouped[_series_key(sample.attributes)].append(sample)

    for series in grouped.values():
        previous_end_ns: int | None = None
        for sample in sorted(
            series,
            key=lambda point: (point.start_time_ns, point.observed_at_ns),
        ):
            if previous_end_ns is not None and sample.start_time_ns != previous_end_ns:
                relation = (
                    "duplicate or overlapping"
                    if sample.start_time_ns < previous_end_ns
                    else "gapped"
                )
                raise MetricAggregationError(f"{metric_name} contains {relation} delta intervals")
            previous_end_ns = sample.observed_at_ns
    return selected


def _interval_coverage(samples: Sequence[MetricPoint]) -> MetricIntervalCoverage:
    return tuple(
        sorted(
            (
                _series_key(sample.attributes),
                sample.start_time_ns,
                sample.observed_at_ns,
            )
            for sample in samples
        )
    )


def require_window_coverage(
    coverage: MetricIntervalCoverage,
    *,
    metric_name: str,
    window_start_ns: int,
    window_end_ns: int,
    tolerance_ns: int = METRIC_WINDOW_COVERAGE_TOLERANCE_NS,
) -> None:
    """Require every metric series to cover nearly all of the declared window."""

    if tolerance_ns < 0:
        raise ValueError("metric coverage tolerance cannot be negative")
    window_duration_ns = window_end_ns - window_start_ns
    if window_duration_ns <= 0:
        raise ValueError("metric evaluation window must have positive duration")
    effective_tolerance_ns = min(
        tolerance_ns,
        int(window_duration_ns * METRIC_WINDOW_MAX_UNCOVERED_FRACTION),
    )
    if not coverage:
        raise MetricAggregationError(f"{metric_name} has no interval coverage")
    by_series: dict[MetricSeriesKey, list[tuple[int, int]]] = defaultdict(list)
    for series_key, start_ns, end_ns in coverage:
        by_series[series_key].append((start_ns, end_ns))
    for intervals in by_series.values():
        ordered = sorted(intervals)
        for (_, previous_end_ns), (start_ns, _) in zip(
            ordered,
            ordered[1:],
            strict=False,
        ):
            if start_ns != previous_end_ns:
                raise MetricAggregationError(
                    f"{metric_name} does not continuously cover the evaluation window"
                )
        first_start_ns = ordered[0][0]
        last_end_ns = ordered[-1][1]
        if abs(first_start_ns - window_start_ns) > effective_tolerance_ns:
            raise MetricAggregationError(
                f"{metric_name} starts outside the evaluation-window coverage tolerance"
            )
        if abs(last_end_ns - window_end_ns) > effective_tolerance_ns:
            raise MetricAggregationError(
                f"{metric_name} ends outside the evaluation-window coverage tolerance"
            )
        uncovered_ns = max(0, first_start_ns - window_start_ns) + max(
            0, window_end_ns - last_end_ns
        )
        if uncovered_ns > effective_tolerance_ns:
            raise MetricAggregationError(
                f"{metric_name} does not cover enough of the evaluation window"
            )


def histogram_window_coverage(
    samples: Sequence[HistogramSample],
    *,
    window_start_ns: int,
    window_end_ns: int,
) -> MetricIntervalCoverage:
    """Return the contribution intervals used by a histogram window aggregate."""

    if not samples:
        raise MetricAggregationError("no histogram samples")
    coverage = _interval_coverage(
        _histogram_contributions(
            samples,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
        )
    )
    return tuple(
        (
            series_key,
            max(start_ns, window_start_ns),
            min(end_ns, window_end_ns),
        )
        for series_key, start_ns, end_ns in coverage
        if max(start_ns, window_start_ns) < min(end_ns, window_end_ns)
    )


def _matching_window(
    samples: Sequence[MetricPoint],
    *,
    window_start_ns: int,
    window_end_ns: int,
) -> list[MetricPoint]:
    return [
        sample for sample in samples if window_start_ns <= sample.observed_at_ns <= window_end_ns
    ]


def _subtract_histograms(
    latest: HistogramSample,
    baseline: HistogramSample,
) -> HistogramSample:
    if (
        latest.name != baseline.name
        or latest.unit != baseline.unit
        or latest.attributes != baseline.attributes
    ):
        raise MetricAggregationError(
            "cumulative histogram identity changed between baseline and current point"
        )
    if latest.explicit_bounds != baseline.explicit_bounds:
        raise MetricAggregationError("cumulative histogram bucket boundaries changed")
    bucket_counts = tuple(
        current - previous
        for current, previous in zip(
            latest.bucket_counts,
            baseline.bucket_counts,
            strict=True,
        )
    )
    count = latest.count - baseline.count
    if count < 0 or any(value < 0 for value in bucket_counts):
        raise MetricAggregationError("cumulative histogram counters moved backwards")
    if (latest.sum is None) != (baseline.sum is None):
        raise MetricAggregationError("cumulative histogram sum availability changed")
    sum_value = (
        latest.sum - baseline.sum if latest.sum is not None and baseline.sum is not None else None
    )
    return HistogramSample(
        name=latest.name,
        unit=latest.unit,
        observed_at_ns=latest.observed_at_ns,
        count=count,
        bucket_counts=bucket_counts,
        explicit_bounds=latest.explicit_bounds,
        attributes=latest.attributes,
        temporality="delta",
        start_time_ns=baseline.observed_at_ns,
        sum=sum_value,
    )


def _histogram_contributions(
    samples: Sequence[HistogramSample],
    *,
    window_start_ns: int,
    window_end_ns: int,
) -> list[HistogramSample]:
    temporalities = {sample.temporality for sample in samples}
    if len(temporalities) != 1:
        raise MetricAggregationError("mixed histogram aggregation temporalities")
    temporality = next(iter(temporalities))
    if temporality == "unspecified":
        raise MetricAggregationError("histogram aggregation temporality is unspecified")
    if temporality == "delta":
        return [
            sample
            for sample in _validated_delta_points(
                samples,
                window_start_ns=window_start_ns,
                window_end_ns=window_end_ns,
                metric_name=samples[0].name,
            )
            if isinstance(sample, HistogramSample)
        ]

    grouped: dict[
        tuple[tuple[tuple[str, str, MetricAttribute], ...], int],
        list[HistogramSample],
    ] = defaultdict(list)
    for sample in samples:
        if sample.observed_at_ns <= window_end_ns:
            grouped[(_series_key(sample.attributes), sample.start_time_ns)].append(sample)

    contributions: list[HistogramSample] = []
    for series in grouped.values():
        ordered = sorted(series, key=lambda sample: sample.observed_at_ns)
        latest = ordered[-1]
        if latest.observed_at_ns < window_start_ns:
            continue
        if latest.start_time_ns >= window_start_ns:
            contributions.append(latest)
            continue
        baselines = [
            sample
            for sample in ordered
            if sample.start_time_ns == latest.start_time_ns
            and sample.observed_at_ns <= window_start_ns
            and sample.observed_at_ns < latest.observed_at_ns
        ]
        if not baselines:
            raise MetricAggregationError(
                "cumulative histogram has no baseline at the evaluation-window start"
            )
        contributions.append(_subtract_histograms(latest, baselines[-1]))
    return contributions


def _merge_histograms(samples: Sequence[HistogramSample]) -> HistogramSample:
    if not samples:
        raise MetricAggregationError("no histogram events in evaluation window")
    names = {sample.name for sample in samples}
    units = {sample.unit for sample in samples}
    if len(names) != 1 or len(units) != 1:
        raise MetricAggregationError("incompatible histogram names or units")
    bounds = samples[0].explicit_bounds
    if any(sample.explicit_bounds != bounds for sample in samples[1:]):
        raise MetricAggregationError("incompatible histogram bucket boundaries")
    bucket_counts = tuple(
        sum(sample.bucket_counts[index] for sample in samples) for index in range(len(bounds) + 1)
    )
    sums = [sample.sum for sample in samples]
    minima = [sample.min for sample in samples]
    maxima = [sample.max for sample in samples]
    return HistogramSample(
        name=samples[0].name,
        unit=samples[0].unit,
        observed_at_ns=max(sample.observed_at_ns for sample in samples),
        count=sum(sample.count for sample in samples),
        bucket_counts=bucket_counts,
        explicit_bounds=bounds,
        attributes={},
        temporality="delta",
        sum=sum(value for value in sums if value is not None)
        if all(value is not None for value in sums)
        else None,
        min=min(value for value in minima if value is not None)
        if all(value is not None for value in minima)
        else None,
        max=max(value for value in maxima if value is not None)
        if all(value is not None for value in maxima)
        else None,
    )


def _histogram_quantile_bounds(
    histogram: HistogramSample,
    quantile: float,
) -> tuple[float, float]:
    if histogram.count == 0:
        raise MetricAggregationError("histogram has no recorded events")
    rank = max(1, math.ceil(histogram.count * quantile))
    cumulative = 0
    for index, count in enumerate(histogram.bucket_counts):
        cumulative += count
        if cumulative < rank:
            continue
        lower = histogram.explicit_bounds[index - 1] if index > 0 else histogram.min
        upper = (
            histogram.explicit_bounds[index]
            if index < len(histogram.explicit_bounds)
            else histogram.max
        )
        if lower is None or upper is None:
            raise MetricAggregationError(
                "histogram quantile bounds require recorded min and max values"
            )
        if histogram.min is not None:
            lower = max(lower, histogram.min)
        if histogram.max is not None:
            upper = min(upper, histogram.max)
        if lower > upper:
            raise MetricAggregationError("histogram quantile bounds are inconsistent")
        return lower, upper
    raise MetricAggregationError("histogram bucket counts do not cover count")


def _histogram_quantile(histogram: HistogramSample, quantile: float) -> float:
    return _histogram_quantile_bounds(histogram, quantile)[1]


def _merged_histogram(
    samples: Sequence[HistogramSample],
    *,
    window_start_ns: int,
    window_end_ns: int,
) -> HistogramSample:
    return _merge_histograms(
        _histogram_contributions(
            samples,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
        )
    )


def aggregate_metric_points(
    samples: Sequence[MetricPoint],
    aggregation: str,
    *,
    window_start_ns: int,
    window_end_ns: int,
) -> float | int:
    """Aggregate scalar or explicit-bucket points without expanding histogram events."""

    if not samples:
        raise MetricAggregationError("no metric samples")
    if all(isinstance(sample, MetricSample) for sample in samples):
        window = _matching_window(
            samples,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
        )
        if not window:
            raise MetricAggregationError("no scalar samples in evaluation window")
        if (
            len({sample.instrument_kind for sample in window if isinstance(sample, MetricSample)})
            != 1
        ):
            raise MetricAggregationError("mixed scalar metric instrument kinds")
        if any(
            sample.instrument_kind == "sum" for sample in window if isinstance(sample, MetricSample)
        ):
            raise MetricAggregationError(
                "OTLP Sum cannot use generic scalar aggregation; "
                "evaluate its temporality-aware counter delta instead"
            )
        return _aggregate(
            aggregation,
            [sample.value for sample in window if isinstance(sample, MetricSample)],
        )
    if not all(isinstance(sample, HistogramSample) for sample in samples):
        raise MetricAggregationError("mixed scalar and histogram points")

    histograms = [sample for sample in samples if isinstance(sample, HistogramSample)]
    merged = _merged_histogram(
        histograms,
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
    )
    if aggregation == "count":
        return merged.count
    if aggregation == "mean":
        if merged.sum is None:
            raise MetricAggregationError("histogram mean requires a recorded sum")
        if merged.count == 0:
            raise MetricAggregationError("histogram has no recorded events")
        return merged.sum / merged.count
    if aggregation == "min":
        if merged.min is None:
            raise MetricAggregationError("histogram min was not recorded")
        return merged.min
    if aggregation == "max":
        if merged.max is None:
            raise MetricAggregationError("histogram max was not recorded")
        return merged.max
    if aggregation == "p50":
        return _histogram_quantile(merged, 0.50)
    if aggregation == "p95":
        return _histogram_quantile(merged, 0.95)
    if aggregation == "p99":
        return _histogram_quantile(merged, 0.99)
    raise MetricAggregationError(f"unsupported aggregation: {aggregation}")


def counter_window_aggregate(
    samples: Sequence[MetricPoint],
    metric_name: str,
    *,
    attribute_match: Mapping[str, MetricAttribute],
    expected_unit: str,
    window_start_ns: int,
    window_end_ns: int,
) -> CounterWindowAggregate:
    """Return a monotonic Sum increase and the exact intervals that produced it."""

    matching = [
        sample
        for sample in samples
        if sample.name == metric_name
        and all(sample.attributes.get(key) == value for key, value in attribute_match.items())
    ]
    if not matching:
        raise MetricAggregationError(f"no counter points for {metric_name}")
    units = {sample.unit for sample in matching}
    if units != {expected_unit}:
        raise MetricAggregationError(
            f"{metric_name} requires unit {expected_unit}; observed {sorted(units)}"
        )
    if not all(
        isinstance(sample, MetricSample) and sample.instrument_kind == "sum" and sample.monotonic
        for sample in matching
    ):
        raise MetricAggregationError(f"{metric_name} must be a monotonic OTLP Sum")
    counters = [sample for sample in matching if isinstance(sample, MetricSample)]
    if any(sample.value < 0 for sample in counters):
        raise MetricAggregationError(f"{metric_name} contains a negative counter value")
    temporalities = {sample.temporality for sample in counters}
    if len(temporalities) != 1:
        raise MetricAggregationError(f"{metric_name} mixes aggregation temporalities")
    temporality = next(iter(temporalities))
    if temporality == "unspecified":
        raise MetricAggregationError(f"{metric_name} has unspecified aggregation temporality")
    if temporality == "delta":
        points = [
            sample
            for sample in _validated_delta_points(
                counters,
                window_start_ns=window_start_ns,
                window_end_ns=window_end_ns,
                metric_name=metric_name,
            )
            if isinstance(sample, MetricSample)
        ]
        if not points:
            raise MetricAggregationError(
                f"{metric_name} has no delta points in the evaluation window"
            )
        if any(sample.value < 0 for sample in points):
            raise MetricAggregationError(f"{metric_name} contains a negative delta")
        delta_coverage = _interval_coverage(points)
        return CounterWindowAggregate(
            total=sum(sample.value for sample in points),
            coverage=delta_coverage,
        )

    grouped: dict[
        tuple[MetricSeriesKey, int],
        list[MetricSample],
    ] = defaultdict(list)
    for sample in counters:
        if sample.observed_at_ns <= window_end_ns:
            grouped[(_series_key(sample.attributes), sample.start_time_ns)].append(sample)
    total = 0.0
    observed_series = 0
    cumulative_coverage: list[tuple[MetricSeriesKey, int, int]] = []
    for (series_key, _), series in grouped.items():
        ordered = sorted(series, key=lambda sample: sample.observed_at_ns)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current.observed_at_ns == previous.observed_at_ns:
                raise MetricAggregationError(
                    f"{metric_name} contains duplicate cumulative observations"
                )
            if current.value < previous.value:
                raise MetricAggregationError(f"{metric_name} cumulative value moved backwards")
        latest = ordered[-1]
        if latest.observed_at_ns < window_start_ns:
            continue
        if latest.start_time_ns >= window_start_ns:
            increase = latest.value
            interval_start_ns = latest.start_time_ns
        else:
            baselines = [
                sample
                for sample in ordered
                if sample.start_time_ns == latest.start_time_ns
                and sample.observed_at_ns <= window_start_ns
                and sample.observed_at_ns < latest.observed_at_ns
            ]
            if not baselines:
                raise MetricAggregationError(
                    f"{metric_name} has no cumulative baseline at the evaluation-window start"
                )
            baseline = baselines[-1]
            increase = latest.value - baseline.value
            interval_start_ns = baseline.observed_at_ns
        if increase < 0:
            raise MetricAggregationError(f"{metric_name} cumulative value moved backwards")
        if interval_start_ns >= latest.observed_at_ns:
            raise MetricAggregationError(
                f"{metric_name} contains an empty or reversed cumulative interval"
            )
        total += increase
        cumulative_coverage.append((series_key, interval_start_ns, latest.observed_at_ns))
        observed_series += 1
    if observed_series == 0:
        raise MetricAggregationError(
            f"{metric_name} has no cumulative points in the evaluation window"
        )
    ordered_coverage = tuple(sorted(cumulative_coverage))
    by_series: dict[MetricSeriesKey, list[tuple[int, int]]] = defaultdict(list)
    for series_key, start_ns, end_ns in ordered_coverage:
        by_series[series_key].append((start_ns, end_ns))
    for intervals in by_series.values():
        previous_end_ns: int | None = None
        for start_ns, end_ns in intervals:
            if previous_end_ns is not None and start_ns < previous_end_ns:
                raise MetricAggregationError(
                    f"{metric_name} contains overlapping cumulative intervals"
                )
            previous_end_ns = end_ns
    return CounterWindowAggregate(total=total, coverage=ordered_coverage)


def _compare(operator: str, observed: float | int, threshold: float) -> bool:
    comparisons = {
        "lt": observed < threshold,
        "lte": observed <= threshold,
        "eq": observed == threshold,
        "gte": observed >= threshold,
        "gt": observed > threshold,
    }
    return comparisons[operator]


def _histogram_quantile_evaluation(
    samples: Sequence[MetricPoint],
    aggregation: str,
    operator: str,
    threshold: float,
    *,
    window_start_ns: int,
    window_end_ns: int,
) -> tuple[float, bool]:
    quantile = {
        "p50": 0.50,
        "p95": 0.95,
        "p99": 0.99,
    }[aggregation]
    merged = _merged_histogram(
        [sample for sample in samples if isinstance(sample, HistogramSample)],
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
    )
    lower, upper = _histogram_quantile_bounds(merged, quantile)
    if operator in {"lt", "lte"}:
        return upper, _compare(operator, upper, threshold)
    if operator in {"gt", "gte"}:
        return lower, _compare(operator, lower, threshold)
    if lower != upper:
        raise MetricAggregationError(
            "histogram quantile equality cannot be proven from a non-zero-width bucket"
        )
    return lower, _compare(operator, lower, threshold)


def evaluate_metric_assertions(
    assertions: Sequence[Mapping[str, Any]],
    samples: Sequence[MetricPoint],
    *,
    window_start_ns: int | None = None,
    window_end_ns: int | None = None,
) -> tuple[AssertionEvaluation, ...]:
    """Evaluate contract metric assertions against canonical metric samples."""

    if (window_start_ns is None) != (window_end_ns is None):
        raise ValueError("metric evaluation window requires both start and end")
    if (
        window_start_ns is not None
        and window_end_ns is not None
        and window_end_ns < window_start_ns
    ):
        raise ValueError("metric evaluation window ends before it starts")

    grouped: dict[str, list[MetricPoint]] = defaultdict(list)
    for sample in samples:
        grouped[sample.name].append(sample)

    evaluations: list[AssertionEvaluation] = []
    for assertion in assertions:
        assertion_id = assertion["assertion_id"]
        metric_name = assertion["metric_name"]
        attribute_match = assertion.get("attribute_match", {})
        metric_samples = [
            sample
            for sample in grouped.get(metric_name, [])
            if all(sample.attributes.get(key) == value for key, value in attribute_match.items())
        ]
        if not metric_samples:
            evaluations.append(
                AssertionEvaluation(
                    assertion_id=assertion_id,
                    status="error",
                    observed_value=None,
                    unit=assertion["unit"],
                    message=(
                        f"no samples for {metric_name} matching "
                        f"{dict(sorted(attribute_match.items()))}"
                    ),
                )
            )
            continue

        end_ns = (
            window_end_ns
            if window_end_ns is not None
            else max(sample.observed_at_ns for sample in metric_samples)
        )
        start_ns = end_ns - int(float(assertion["window_sec"]) * 1_000_000_000)
        if window_start_ns is not None:
            start_ns = max(start_ns, window_start_ns)
        window = [
            sample for sample in metric_samples if start_ns <= sample.observed_at_ns <= end_ns
        ]
        if not window:
            evaluations.append(
                AssertionEvaluation(
                    assertion_id=assertion_id,
                    status="error",
                    observed_value=None,
                    unit=assertion["unit"],
                    message=(
                        f"no samples for {metric_name} in evaluation window [{start_ns}, {end_ns}]"
                    ),
                )
            )
            continue
        units = {sample.unit for sample in window}
        if units != {assertion["unit"]}:
            evaluations.append(
                AssertionEvaluation(
                    assertion_id=assertion_id,
                    status="error",
                    observed_value=None,
                    unit=assertion["unit"],
                    message=f"expected unit {assertion['unit']}; observed {sorted(units)}",
                )
            )
            continue

        try:
            histogram_quantile = assertion["aggregation"] in {"p50", "p95", "p99"} and all(
                isinstance(sample, HistogramSample) for sample in metric_samples
            )
            if histogram_quantile:
                observed, passed = _histogram_quantile_evaluation(
                    metric_samples,
                    assertion["aggregation"],
                    assertion["operator"],
                    assertion["threshold"],
                    window_start_ns=start_ns,
                    window_end_ns=end_ns,
                )
            else:
                observed = aggregate_metric_points(
                    metric_samples,
                    assertion["aggregation"],
                    window_start_ns=start_ns,
                    window_end_ns=end_ns,
                )
                passed = _compare(
                    assertion["operator"],
                    observed,
                    assertion["threshold"],
                )
            if all(isinstance(sample, HistogramSample) for sample in metric_samples):
                histogram_samples = [
                    sample for sample in metric_samples if isinstance(sample, HistogramSample)
                ]
                require_window_coverage(
                    histogram_window_coverage(
                        histogram_samples,
                        window_start_ns=start_ns,
                        window_end_ns=end_ns,
                    ),
                    metric_name=metric_name,
                    window_start_ns=start_ns,
                    window_end_ns=end_ns,
                )
        except MetricAggregationError as error:
            evaluations.append(
                AssertionEvaluation(
                    assertion_id=assertion_id,
                    status="error",
                    observed_value=None,
                    unit=assertion["unit"],
                    message=str(error),
                )
            )
            continue
        message = "" if passed else f"threshold {assertion['operator']} {assertion['threshold']}"
        evaluations.append(
            AssertionEvaluation(
                assertion_id=assertion_id,
                status="passed" if passed else "failed",
                observed_value=observed,
                unit=assertion["unit"],
                message=message,
            )
        )
    return tuple(evaluations)

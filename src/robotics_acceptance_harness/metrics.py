from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class MetricSample:
    name: str
    value: float
    unit: str
    observed_at_ns: int


@dataclass(frozen=True, slots=True)
class AssertionEvaluation:
    assertion_id: str
    status: Literal["passed", "failed", "error"]
    observed_value: float | int | None
    unit: str
    message: str = ""


def _percentile(values: Sequence[float], quantile: float) -> float:
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
        return _percentile(values, 0.50)
    if name == "p95":
        return _percentile(values, 0.95)
    if name == "p99":
        return _percentile(values, 0.99)
    if name == "count":
        return len(values)
    raise ValueError(f"unsupported aggregation: {name}")


def _compare(operator: str, observed: float | int, threshold: float) -> bool:
    comparisons = {
        "lt": observed < threshold,
        "lte": observed <= threshold,
        "eq": observed == threshold,
        "gte": observed >= threshold,
        "gt": observed > threshold,
    }
    return comparisons[operator]


def evaluate_metric_assertions(
    assertions: Sequence[Mapping[str, Any]],
    samples: Sequence[MetricSample],
) -> tuple[AssertionEvaluation, ...]:
    """Evaluate contract metric assertions against canonical metric samples."""

    grouped: dict[str, list[MetricSample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.name].append(sample)

    evaluations: list[AssertionEvaluation] = []
    for assertion in assertions:
        assertion_id = assertion["assertion_id"]
        metric_name = assertion["metric_name"]
        metric_samples = grouped.get(metric_name, [])
        if not metric_samples:
            evaluations.append(
                AssertionEvaluation(
                    assertion_id=assertion_id,
                    status="error",
                    observed_value=None,
                    unit=assertion["unit"],
                    message=f"no samples for {metric_name}",
                )
            )
            continue

        end_ns = max(sample.observed_at_ns for sample in metric_samples)
        start_ns = end_ns - int(float(assertion["window_sec"]) * 1_000_000_000)
        window = [sample for sample in metric_samples if sample.observed_at_ns >= start_ns]
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

        observed = _aggregate(assertion["aggregation"], [sample.value for sample in window])
        passed = _compare(assertion["operator"], observed, assertion["threshold"])
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


__all__ = ["AssertionEvaluation", "MetricSample", "evaluate_metric_assertions"]

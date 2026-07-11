from __future__ import annotations

import pytest

from robotics_acceptance_harness.metrics import MetricSample, evaluate_metric_assertions


def assertion(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "assertion_id": "latency",
        "kind": "metric",
        "metric_name": "robotics.inference.latency",
        "unit": "ms",
        "aggregation": "p95",
        "operator": "lte",
        "threshold": 100,
        "window_sec": 10,
    }
    value.update(overrides)
    return value


def samples() -> list[MetricSample]:
    return [
        MetricSample("robotics.inference.latency", value, "ms", index * 1_000_000_000)
        for index, value in enumerate([10, 20, 30, 40, 50])
    ]


@pytest.mark.parametrize(
    ("aggregation", "expected"),
    [
        ("min", 10),
        ("max", 50),
        ("mean", 30),
        ("p50", 30),
        ("p95", 48),
        ("p99", 49.6),
        ("count", 5),
    ],
)
def test_metric_aggregations(aggregation: str, expected: float) -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation=aggregation, threshold=100)],
        samples(),
    )[0]
    assert result.status == "passed"
    assert result.observed_value == pytest.approx(expected)


def test_metric_window_excludes_old_samples() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="mean", window_sec=2, threshold=45)],
        samples(),
    )[0]
    assert result.observed_value == 40
    assert result.status == "passed"


def test_failed_threshold_is_reported_without_exception() -> None:
    result = evaluate_metric_assertions([assertion(threshold=20)], samples())[0]
    assert result.status == "failed"
    assert result.message == "threshold lte 20"


def test_missing_metric_and_wrong_unit_are_errors() -> None:
    missing = evaluate_metric_assertions(
        [assertion(metric_name="robotics.missing")],
        samples(),
    )[0]
    wrong_unit = evaluate_metric_assertions(
        [assertion(unit="s")],
        samples(),
    )[0]
    assert missing.status == "error"
    assert wrong_unit.status == "error"

from __future__ import annotations

import pytest

from robotics_acceptance_harness.metrics import (
    HistogramSample,
    MetricSample,
    MetricTemporality,
    evaluate_metric_assertions,
)


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


def test_metric_window_is_anchored_to_the_execution_window() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="max", threshold=100)],
        [
            MetricSample(
                "robotics.inference.latency",
                10,
                "ms",
                1_000_000_000,
            )
        ],
        window_start_ns=20_000_000_000,
        window_end_ns=30_000_000_000,
    )[0]

    assert result.status == "error"
    assert result.observed_value is None
    assert "evaluation window" in result.message


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


def test_attribute_match_keeps_domains_and_channels_separate() -> None:
    attributed = [
        MetricSample(
            "robotics.inference.latency",
            10,
            "ms",
            1,
            {"domain.id": "camera", "channel": "/camera/image"},
        ),
        MetricSample(
            "robotics.inference.latency",
            500,
            "ms",
            1,
            {"domain.id": "lidar", "channel": "/points"},
        ),
    ]
    result = evaluate_metric_assertions(
        [
            assertion(
                aggregation="max",
                threshold=20,
                attribute_match={"domain.id": "camera", "channel": "/camera/image"},
            )
        ],
        attributed,
    )[0]

    assert result.status == "passed"
    assert result.observed_value == 10


def histogram(
    *,
    observed_at_ns: int,
    count: int,
    bucket_counts: tuple[int, ...],
    bounds: tuple[float, ...] = (10, 20, 50),
    sum_value: float | None = None,
    minimum: float | None = 1,
    maximum: float | None = 49,
    temporality: MetricTemporality = "delta",
    start_time_ns: int = 0,
    unit: str = "ms",
) -> HistogramSample:
    return HistogramSample(
        name="robotics.inference.latency",
        unit=unit,
        observed_at_ns=observed_at_ns,
        count=count,
        bucket_counts=bucket_counts,
        explicit_bounds=bounds,
        temporality=temporality,
        start_time_ns=start_time_ns,
        sum=sum_value,
        min=minimum,
        max=maximum,
    )


@pytest.mark.parametrize(
    ("aggregation", "expected"),
    [
        ("count", 5),
        ("mean", 20),
        ("p50", 20),
        ("p95", 49),
        ("max", 49),
    ],
)
def test_explicit_histogram_uses_event_distribution(
    aggregation: str,
    expected: float,
) -> None:
    points = [
        histogram(
            observed_at_ns=1,
            count=2,
            bucket_counts=(1, 1, 0, 0),
            sum_value=20,
            maximum=15,
        ),
        histogram(
            observed_at_ns=2,
            start_time_ns=1,
            count=3,
            bucket_counts=(0, 1, 2, 0),
            sum_value=80,
        ),
    ]

    result = evaluate_metric_assertions(
        [assertion(aggregation=aggregation, threshold=100)],
        points,
        window_start_ns=0,
        window_end_ns=2,
    )[0]

    assert result.status == "passed"
    assert result.observed_value == pytest.approx(expected)


def test_cumulative_histogram_uses_window_baseline() -> None:
    points = [
        histogram(
            observed_at_ns=1,
            count=2,
            bucket_counts=(1, 1, 0, 0),
            sum_value=20,
            temporality="cumulative",
        ),
        histogram(
            observed_at_ns=3,
            count=5,
            bucket_counts=(1, 2, 2, 0),
            sum_value=100,
            temporality="cumulative",
        ),
    ]

    result = evaluate_metric_assertions(
        [assertion(aggregation="count", threshold=3, operator="eq")],
        points,
        window_start_ns=2,
        window_end_ns=3,
    )[0]

    assert result.status == "passed"
    assert result.observed_value == 3


def test_cumulative_histogram_preserves_series_across_reset() -> None:
    points = [
        histogram(
            observed_at_ns=2,
            count=2,
            bucket_counts=(1, 1, 0, 0),
            sum_value=20,
            temporality="cumulative",
            start_time_ns=0,
        ),
        histogram(
            observed_at_ns=5,
            count=3,
            bucket_counts=(0, 1, 2, 0),
            sum_value=80,
            temporality="cumulative",
            start_time_ns=2,
        ),
    ]

    result = evaluate_metric_assertions(
        [assertion(aggregation="count", threshold=5, operator="eq")],
        points,
        window_start_ns=0,
        window_end_ns=5,
    )[0]

    assert result.status == "passed"
    assert result.observed_value == 5


def test_rejects_mixed_points_and_incompatible_histogram_buckets() -> None:
    mixed = evaluate_metric_assertions(
        [assertion()],
        [
            samples()[0],
            histogram(
                observed_at_ns=2,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            ),
        ],
    )[0]
    incompatible = evaluate_metric_assertions(
        [assertion()],
        [
            histogram(
                observed_at_ns=1,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            ),
            histogram(
                observed_at_ns=2,
                start_time_ns=1,
                count=1,
                bucket_counts=(1, 0, 0),
                bounds=(10, 50),
                sum_value=5,
            ),
        ],
    )[0]

    assert mixed.status == "error"
    assert "mixed scalar and histogram" in mixed.message
    assert incompatible.status == "error"
    assert "incompatible histogram bucket" in incompatible.message


def test_histogram_quantile_is_capped_by_recorded_maximum() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="p95", threshold=0.5)],
        [
            histogram(
                observed_at_ns=1,
                count=30,
                bucket_counts=(30, 0),
                bounds=(1,),
                sum_value=15,
                minimum=0.5,
                maximum=0.5,
            )
        ],
        window_start_ns=0,
        window_end_ns=1,
    )[0]

    assert result.status == "passed"
    assert result.observed_value == 0.5


def test_histogram_quantile_does_not_use_upper_bound_to_prove_gte() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="p95", operator="gte", threshold=1.5)],
        [
            histogram(
                observed_at_ns=1,
                count=100,
                bucket_counts=(0, 95, 5),
                bounds=(1, 2),
                sum_value=150,
                minimum=1.1,
                maximum=2.5,
            )
        ],
        window_start_ns=0,
        window_end_ns=1,
    )[0]

    assert result.status == "failed"
    assert result.observed_value == 1.1


def test_histogram_quantile_equality_requires_an_exact_bucket() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="p95", operator="eq", threshold=2)],
        [
            histogram(
                observed_at_ns=1,
                count=100,
                bucket_counts=(0, 95, 5),
                bounds=(1, 2),
                sum_value=150,
                minimum=1.1,
                maximum=2.5,
            )
        ],
        window_start_ns=0,
        window_end_ns=1,
    )[0]

    assert result.status == "error"
    assert "equality cannot be proven" in result.message


def test_delta_histogram_rejects_interval_crossing_window_start() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="count", operator="eq", threshold=100)],
        [
            histogram(
                observed_at_ns=110,
                start_time_ns=90,
                count=100,
                bucket_counts=(100, 0, 0, 0),
                sum_value=500,
            )
        ],
        window_start_ns=100,
        window_end_ns=120,
    )[0]

    assert result.status == "error"
    assert "no histogram events" in result.message


@pytest.mark.parametrize(
    "points",
    [
        [
            histogram(
                observed_at_ns=1,
                start_time_ns=0,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            ),
            histogram(
                observed_at_ns=1,
                start_time_ns=0,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            ),
        ],
        [
            histogram(
                observed_at_ns=2,
                start_time_ns=0,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            ),
            histogram(
                observed_at_ns=3,
                start_time_ns=1,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            ),
        ],
    ],
)
def test_delta_histogram_rejects_duplicate_or_overlapping_intervals(
    points: list[HistogramSample],
) -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="count", operator="eq", threshold=2)],
        points,
        window_start_ns=0,
        window_end_ns=3,
    )[0]

    assert result.status == "error"
    assert "duplicate or overlapping delta intervals" in result.message


def test_delta_histogram_accepts_adjacent_intervals() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="count", operator="eq", threshold=2)],
        [
            histogram(
                observed_at_ns=1,
                start_time_ns=0,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            ),
            histogram(
                observed_at_ns=2,
                start_time_ns=1,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            ),
        ],
        window_start_ns=0,
        window_end_ns=2,
    )[0]

    assert result.status == "passed"
    assert result.observed_value == 2


def test_generic_histogram_assertion_requires_full_window_coverage() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="count", operator="eq", threshold=1)],
        [
            histogram(
                observed_at_ns=10_000_000_000,
                start_time_ns=9_000_000_000,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            )
        ],
        window_start_ns=0,
        window_end_ns=10_000_000_000,
    )[0]

    assert result.status == "error"
    assert "coverage tolerance" in result.message


def test_histogram_window_limits_total_uncovered_edges() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="count", operator="eq", threshold=1)],
        [
            histogram(
                observed_at_ns=9_500_000_000,
                start_time_ns=500_000_000,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            )
        ],
        window_start_ns=0,
        window_end_ns=10_000_000_000,
    )[0]

    assert result.status == "error"
    assert "does not cover enough" in result.message


def test_delta_histogram_rejects_gapped_intervals() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="count", operator="eq", threshold=2)],
        [
            histogram(
                observed_at_ns=1,
                start_time_ns=0,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            ),
            histogram(
                observed_at_ns=3,
                start_time_ns=2,
                count=1,
                bucket_counts=(1, 0, 0, 0),
                sum_value=5,
            ),
        ],
        window_start_ns=0,
        window_end_ns=3,
    )[0]

    assert result.status == "error"
    assert "gapped delta intervals" in result.message


def test_generic_metric_assertion_rejects_otlp_sum() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="max", operator="eq", threshold=100)],
        [
            MetricSample(
                "robotics.inference.latency",
                90,
                "ms",
                1,
                instrument_kind="sum",
                temporality="cumulative",
                monotonic=True,
            ),
            MetricSample(
                "robotics.inference.latency",
                100,
                "ms",
                2,
                instrument_kind="sum",
                temporality="cumulative",
                monotonic=True,
            ),
        ],
        window_start_ns=0,
        window_end_ns=2,
    )[0]

    assert result.status == "error"
    assert "OTLP Sum cannot use generic scalar aggregation" in result.message


def test_cumulative_histogram_rejects_baseline_with_another_unit() -> None:
    result = evaluate_metric_assertions(
        [assertion(aggregation="count", operator="eq", threshold=10)],
        [
            histogram(
                observed_at_ns=99,
                count=10,
                bucket_counts=(10, 0, 0, 0),
                sum_value=50,
                temporality="cumulative",
                unit="s",
            ),
            histogram(
                observed_at_ns=120,
                count=20,
                bucket_counts=(20, 0, 0, 0),
                sum_value=100,
                temporality="cumulative",
                unit="ms",
            ),
        ],
        window_start_ns=100,
        window_end_ns=120,
    )[0]

    assert result.status == "error"
    assert "identity changed" in result.message

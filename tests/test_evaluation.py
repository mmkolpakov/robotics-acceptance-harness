from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from robotics_acceptance_harness.documents import LoadedDocument, load_bundle
from robotics_acceptance_harness.evaluation import (
    EvaluationContext,
    EvaluationError,
    evaluate_acceptance,
)
from robotics_acceptance_harness.evidence import VerifiedEvidence
from robotics_acceptance_harness.metrics import (
    AssertionEvaluation,
    MetricDefinitionError,
    MetricSample,
    evaluate_metric_assertions,
    validate_metric_definitions,
)

FIXTURES = Path(__file__).parent / "fixtures" / "simulation"
EVIDENCE_DIGEST = "a" * 64


def context() -> EvaluationContext:
    bundle = load_bundle(
        FIXTURES / "scenario.yaml",
        runtime_path=FIXTURES / "runtime.yaml",
    )
    evidence = VerifiedEvidence(
        LoadedDocument(
            Path("evidence.json"),
            MappingProxyType(
                {
                    "finalized": True,
                    "policy_observation": {
                        "recording_mode": "on_failure",
                        "compression": "zstd",
                        "upload_mode": "local_only",
                        "remote_sink_used": False,
                        "spool_peak_size_bytes": 1,
                        "upload_lag_max_sec": 0,
                    },
                    "segments": [
                        {
                            "size_bytes": 1,
                            "retention_class": "pull-request-7d",
                        }
                    ],
                }
            ),
            "b" * 64,
        ),
        (MappingProxyType({"sha256": EVIDENCE_DIGEST}),),
        MappingProxyType({}),
    )
    return EvaluationContext("run-test", "primary", bundle, evidence, (), 0, 1)


def test_product_evaluator_is_namespaced_and_evidence_bound() -> None:
    def evaluator(_context: EvaluationContext) -> tuple[AssertionEvaluation, ...]:
        return (
            AssertionEvaluation(
                "org.example.sorting.detected",
                "passed",
                1,
                "1",
                source="product",
                namespace="org.example.sorting",
                evidence_sha256=(EVIDENCE_DIGEST,),
            ),
        )

    evaluations = evaluate_acceptance(
        context(),
        evaluators=(("org.example.sorting", evaluator),),
    )

    assert evaluations[-1].assertion_id == "org.example.sorting.detected"
    assert evaluations[-1].source == "product"


def test_product_evaluator_cannot_reference_unverified_evidence() -> None:
    def evaluator(_context: EvaluationContext) -> tuple[AssertionEvaluation, ...]:
        return (
            AssertionEvaluation(
                "org.example.sorting.detected",
                "passed",
                1,
                "1",
                source="product",
                namespace="org.example.sorting",
                evidence_sha256=("f" * 64,),
            ),
        )

    with pytest.raises(EvaluationError, match="unknown evidence"):
        evaluate_acceptance(context(), evaluators=(("org.example.sorting", evaluator),))


def test_product_evaluator_exception_is_a_stable_evaluation_error() -> None:
    def evaluator(_context: EvaluationContext) -> tuple[AssertionEvaluation, ...]:
        raise KeyError("missing calibration")

    with pytest.raises(EvaluationError, match="evaluator 'org.example.sorting' failed"):
        evaluate_acceptance(context(), evaluators=(("org.example.sorting", evaluator),))


def test_installed_distribution_contributes_a_product_evaluator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "example_evaluator.py").write_text(
        """\
from robotics_acceptance_harness import AssertionEvaluation

def evaluate(context):
    return (AssertionEvaluation(
        'org.example.sorting.detected', 'passed', 1, '1',
        source='product', namespace='org.example.sorting',
        evidence_sha256=(next(iter(context.evidence_sha256)),),
    ),)
""",
        encoding="utf-8",
    )
    metadata = tmp_path / "example_evaluator-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: example-evaluator\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "entry_points.txt").write_text(
        "[robotics_acceptance.evaluators]\norg.example.sorting = example_evaluator:evaluate\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    evaluations = evaluate_acceptance(context())

    assert evaluations[-1].assertion_id == "org.example.sorting.detected"


def test_duration_predicate_requires_contiguous_coverage() -> None:
    assertion = {
        "assertion_id": "temperature-stable",
        "kind": "metric_duration",
        "metric_name": "org.example.temperature",
        "unit": "C",
        "operator": "lte",
        "threshold": 10,
        "window_sec": 10,
        "max_sample_gap_sec": 5,
        "duration_requirement": {"kind": "minimum_contiguous", "duration_sec": 8},
        "attribute_match": {},
    }
    samples = (
        MetricSample("org.example.temperature", 8, "C", 0),
        MetricSample("org.example.temperature", 9, "C", 5_000_000_000),
        MetricSample("org.example.temperature", 9, "C", 10_000_000_000),
    )

    evaluation = evaluate_metric_assertions(
        (assertion,),
        samples,
        window_start_ns=0,
        window_end_ns=10_000_000_000,
    )[0]

    assert evaluation.status == "passed"
    assert evaluation.observed_value == 10


def test_duration_predicate_never_merges_distinct_attribute_series() -> None:
    assertion = {
        "assertion_id": "temperature-stable",
        "kind": "metric_duration",
        "metric_name": "org.example.temperature",
        "unit": "C",
        "operator": "lte",
        "threshold": 10,
        "window_sec": 10,
        "max_sample_gap_sec": 6,
        "duration_requirement": {"kind": "minimum_contiguous", "duration_sec": 8},
        "attribute_match": {},
    }
    samples = (
        MetricSample("org.example.temperature", 8, "C", 0, {"sensor": "a"}),
        MetricSample(
            "org.example.temperature",
            8,
            "C",
            5_000_000_000,
            {"sensor": "b"},
        ),
        MetricSample(
            "org.example.temperature",
            8,
            "C",
            10_000_000_000,
            {"sensor": "a"},
        ),
    )

    evaluation = evaluate_metric_assertions(
        (assertion,),
        samples,
        window_start_ns=0,
        window_end_ns=10_000_000_000,
    )[0]

    assert evaluation.status == "error"
    assert "exactly one attribute series" in evaluation.message


def test_missing_declared_metric_becomes_an_error_result() -> None:
    definitions = (
        {
            "metric_name": "org.example.temperature",
            "unit": "C",
            "instrument_kind": "gauge",
            "temporality": "instantaneous",
        },
    )
    assertion = {
        "assertion_id": "temperature",
        "kind": "metric",
        "metric_name": "org.example.temperature",
        "unit": "C",
        "operator": "lte",
        "threshold": 10,
        "aggregation": "max",
        "window_sec": 10,
        "attribute_match": {},
    }

    validate_metric_definitions(definitions, ())
    evaluation = evaluate_metric_assertions((assertion,), ())[0]

    assert evaluation.status == "error"
    assert "no samples" in evaluation.message


def test_metric_definition_rejects_instrument_drift() -> None:
    definitions = (
        {
            "metric_name": "org.example.temperature",
            "unit": "C",
            "instrument_kind": "gauge",
            "temporality": "instantaneous",
        },
    )
    samples = (
        MetricSample(
            "org.example.temperature",
            1,
            "C",
            1,
            instrument_kind="sum",
            temporality="delta",
        ),
    )

    with pytest.raises(MetricDefinitionError, match="expects gauge"):
        validate_metric_definitions(definitions, samples)

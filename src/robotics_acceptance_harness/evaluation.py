from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any, cast

from robotics_acceptance_harness.documents import DocumentBundle
from robotics_acceptance_harness.evidence import VerifiedEvidence
from robotics_acceptance_harness.metrics import (
    AssertionEvaluation,
    MetricPoint,
    evaluate_metric_assertions,
    validate_metric_definitions,
)
from robotics_acceptance_harness.policy import (
    evaluate_data_plane_policy,
    evaluate_evidence_policy,
)

EVALUATOR_ENTRY_POINT_GROUP = "robotics_acceptance.evaluators"


class EvaluationError(ValueError):
    """Raised when an evaluator violates the public extension contract."""

    error_id = "evaluation.invalid"


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Immutable inputs shared by live and offline acceptance evaluation."""

    run_id: str
    domain_id: str
    bundle: DocumentBundle
    evidence: VerifiedEvidence
    metric_samples: tuple[MetricPoint, ...]
    window_start_ns: int
    window_end_ns: int

    @property
    def scenario(self) -> Mapping[str, Any]:
        return self.bundle.scenario.data

    @property
    def runtime(self) -> Mapping[str, Any]:
        return self.bundle.runtime.data

    @property
    def evidence_sha256(self) -> frozenset[str]:
        return frozenset(str(item["sha256"]) for item in self.evidence.links)


type ProductEvaluator = Callable[[EvaluationContext], Iterable[AssertionEvaluation]]


def _load_evaluator(entry_point: EntryPoint) -> ProductEvaluator:
    try:
        evaluator = entry_point.load()
    except Exception as error:
        raise EvaluationError(
            f"cannot load evaluator entry point {entry_point.name!r}: {error}"
        ) from error
    if not callable(evaluator):
        raise EvaluationError(f"entry point {entry_point.name!r} is not callable")
    return cast(ProductEvaluator, evaluator)


def _installed_evaluators() -> tuple[tuple[str, ProductEvaluator], ...]:
    loaded: list[tuple[str, ProductEvaluator]] = []
    for entry_point in sorted(
        entry_points(group=EVALUATOR_ENTRY_POINT_GROUP),
        key=lambda item: (item.name, item.value),
    ):
        loaded.append((entry_point.name, _load_evaluator(entry_point)))
    return tuple(loaded)


def _product_evaluations(
    context: EvaluationContext,
    evaluators: Sequence[tuple[str, ProductEvaluator]],
) -> tuple[AssertionEvaluation, ...]:
    evaluations: list[AssertionEvaluation] = []
    for namespace, evaluator in evaluators:
        if namespace.count(".") < 1:
            raise EvaluationError(
                f"evaluator namespace {namespace!r} must be a reverse-domain name"
            )
        try:
            produced = evaluator(context)
            for evaluation in produced:
                if not isinstance(evaluation, AssertionEvaluation):
                    raise EvaluationError(
                        f"evaluator {namespace!r} returned {type(evaluation).__name__}; "
                        "expected AssertionEvaluation"
                    )
                if evaluation.source != "product" or evaluation.namespace != namespace:
                    raise EvaluationError(
                        f"evaluator {namespace!r} must mark every result as its product namespace"
                    )
                if not evaluation.assertion_id.startswith(f"{namespace}."):
                    raise EvaluationError(
                        f"assertion {evaluation.assertion_id!r} is outside namespace {namespace!r}"
                    )
                if not evaluation.evidence_sha256:
                    raise EvaluationError(
                        f"product assertion {evaluation.assertion_id!r} has no evidence digest"
                    )
                missing = set(evaluation.evidence_sha256) - context.evidence_sha256
                if missing:
                    raise EvaluationError(
                        "product assertion "
                        f"{evaluation.assertion_id!r} references unknown evidence "
                        f"{sorted(missing)}"
                    )
                evaluations.append(evaluation)
        except EvaluationError:
            raise
        except Exception as error:
            raise EvaluationError(f"evaluator {namespace!r} failed: {error}") from error
    return tuple(evaluations)


def evaluate_acceptance(
    context: EvaluationContext,
    *,
    evaluators: Sequence[tuple[str, ProductEvaluator]] | None = None,
) -> tuple[AssertionEvaluation, ...]:
    """Evaluate evidence through the canonical core and installed product evaluators."""

    scenario = context.scenario
    if scenario["schema_version"] == "acceptance-scenario.v5":
        validate_metric_definitions(scenario["metric_definitions"], context.metric_samples)
    evaluations = list(
        evaluate_metric_assertions(
            scenario["assertions"],
            context.metric_samples,
            window_start_ns=context.window_start_ns,
            window_end_ns=context.window_end_ns,
        )
    )
    evaluations.extend(
        evaluate_data_plane_policy(
            scenario["data_plane_policy"],
            context.runtime,
            context.metric_samples,
            domain_id=context.domain_id,
            window_start_ns=context.window_start_ns,
            window_end_ns=context.window_end_ns,
        )
    )
    evaluations.extend(evaluate_evidence_policy(scenario["evidence_policy"], context.evidence))
    evaluations.extend(
        _product_evaluations(
            context,
            tuple(evaluators) if evaluators is not None else _installed_evaluators(),
        )
    )
    identifiers = [item.assertion_id for item in evaluations]
    if len(identifiers) != len(set(identifiers)):
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        raise EvaluationError(f"duplicate assertion identifiers: {duplicates}")
    return tuple(evaluations)


def evaluator_inventory() -> tuple[Mapping[str, str], ...]:
    """Describe installed product evaluators without invoking them."""

    inventory: list[Mapping[str, str]] = []
    for entry_point in sorted(
        entry_points(group=EVALUATOR_ENTRY_POINT_GROUP),
        key=lambda item: (item.name, item.value),
    ):
        assert isinstance(entry_point, EntryPoint)
        _load_evaluator(entry_point)
        inventory.append(
            {
                "namespace": entry_point.name,
                "target": entry_point.value,
                "distribution": (
                    entry_point.dist.name if entry_point.dist is not None else "unknown"
                ),
            }
        )
    return tuple(inventory)


__all__ = [
    "EVALUATOR_ENTRY_POINT_GROUP",
    "AssertionEvaluation",
    "EvaluationContext",
    "EvaluationError",
    "ProductEvaluator",
    "evaluate_acceptance",
    "evaluator_inventory",
]

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic_ns, sleep
from typing import Any, Protocol

from robotics_acceptance_harness.documents import DocumentBundle
from robotics_acceptance_harness.evidence import VerifiedEvidence, load_evidence_index
from robotics_acceptance_harness.metrics import MetricSample, evaluate_metric_assertions
from robotics_acceptance_harness.otel import load_otlp_json_metrics
from robotics_acceptance_harness.readiness import (
    GraphObserver,
    ReadinessResult,
    wait_for_readiness,
)
from robotics_acceptance_harness.result import (
    build_acceptance_result,
    write_junit_xml,
    write_result_json,
)
from robotics_acceptance_harness.ros import RosGraphObserver
from robotics_acceptance_harness.timing import ClockSample, evaluate_timing


class ClockObserver(GraphObserver, Protocol):
    @property
    def clock_samples(self) -> tuple[ClockSample, ...]: ...


class VerificationError(RuntimeError):
    """Raised when an execution cannot produce an acceptance result."""


@dataclass(frozen=True, slots=True)
class VerificationOutputs:
    result: Mapping[str, Any]
    result_path: Path
    junit_path: Path


def _utc_now() -> datetime:
    return datetime.now(UTC)


def explain_bundle(bundle: DocumentBundle) -> dict[str, Any]:
    """Return the validated execution facts without starting an observation."""

    scenario = bundle.scenario.data
    if bundle.scenario.schema_version == "acceptance-scenario.v1":
        return {
            "schema_version": bundle.scenario.schema_version,
            "scenario_sha256": bundle.scenario.sha256,
            "target_environment": scenario["target_environment"],
            "policy": "legacy-simulation-only",
        }
    assert bundle.runtime is not None
    workload_kind = (
        "inference"
        if bundle.runtime.schema_version == "runtime-manifest.v1"
        else bundle.runtime.data["workload"]["kind"]
    )
    return {
        "schema_version": bundle.scenario.schema_version,
        "scenario_id": scenario["scenario_id"],
        "scenario_sha256": bundle.scenario.sha256,
        "runtime_manifest_sha256": bundle.runtime.sha256,
        "execution": dict(scenario["execution"]),
        "workload_kind": workload_kind,
        "model_manifest_sha256": bundle.model.sha256 if bundle.model else None,
        "dataset_manifest_sha256": bundle.dataset.sha256 if bundle.dataset else None,
        "permit_sha256": bundle.permit.sha256 if bundle.permit else None,
        "execution_verification_sha256": (
            bundle.verification.sha256 if bundle.verification else None
        ),
        "expected_ros_graph": {
            kind: len(scenario["expected_ros_graph"][kind])
            for kind in ("topics", "services", "actions", "lifecycle_nodes")
        },
        "evidence": {
            "recording_mode": scenario["evidence_policy"]["recording_mode"],
            "upload_mode": scenario["evidence_policy"]["upload_mode"],
            "retention_class": scenario["evidence_policy"]["retention_class"],
        },
        "policy": (
            "accepted-simulation"
            if scenario["execution"]["target_environment"] == "simulation"
            else (
                "authorized-physical-observation"
                if bundle.scenario.schema_version == "acceptance-scenario.v3"
                else "requires-qualified-physical-release"
            )
        ),
    }


def _latest_metric(samples: Sequence[MetricSample], name: str) -> float | None:
    matches = [sample for sample in samples if sample.name == name]
    if not matches:
        return None
    return max(matches, key=lambda sample: sample.observed_at_ns).value


def _enrich_clock_samples(
    mode: str,
    samples: Sequence[ClockSample],
    metrics: Sequence[MetricSample],
) -> tuple[ClockSample, ...]:
    if mode != "simulation_realtime" or len(samples) < 2:
        return tuple(samples)

    ratios: list[float] = []
    for previous, current in zip(samples, samples[1:], strict=False):
        wall_delta = current.observed_at_ns - previous.observed_at_ns
        source_delta = current.source_time_ns - previous.source_time_ns
        ratios.append(source_delta / wall_delta if wall_delta > 0 else 0.0)
    deadline_ratio = _latest_metric(metrics, "robotics.simulation.deadline_miss_ratio")
    return tuple(
        ClockSample(
            observed_at_ns=sample.observed_at_ns,
            source_time_ns=sample.source_time_ns,
            real_time_factor=ratios[min(index, len(ratios) - 1)],
            deadline_miss_ratio=deadline_ratio,
        )
        for index, sample in enumerate(samples)
    )


def _wait_for_evidence(
    path: str | Path,
    *,
    result_id: str,
    timeout_sec: float,
    poll_interval_sec: float,
    now_ns: Callable[[], int],
    sleep_fn: Callable[[float], None],
) -> VerifiedEvidence:
    source = Path(path).expanduser().resolve()
    deadline_ns = now_ns() + int(timeout_sec * 1_000_000_000)
    while not source.is_file():
        if now_ns() >= deadline_ns:
            raise VerificationError(f"finalized evidence index did not appear: {source}")
        remaining_sec = max(0.0, (deadline_ns - now_ns()) / 1_000_000_000)
        sleep_fn(min(poll_interval_sec, remaining_sec))
    return load_evidence_index(source, expected_run_id=result_id)


def run_verification(
    *,
    bundle: DocumentBundle,
    evidence_index_path: str | Path,
    metric_samples: Sequence[MetricSample] = (),
    otel_metrics_path: str | Path | None = None,
    output_dir: str | Path,
    observer_factory: Callable[..., ClockObserver] = RosGraphObserver,
    now_ns: Callable[[], int] = monotonic_ns,
    sleep_fn: Callable[[float], None] = sleep,
    utc_now: Callable[[], datetime] = _utc_now,
    poll_interval_sec: float = 0.05,
) -> VerificationOutputs:
    """Attach to a running simulation and produce canonical acceptance outputs."""

    if bundle.runtime is None or bundle.scenario.schema_version != "acceptance-scenario.v2":
        raise VerificationError("verify requires acceptance-scenario.v2 and a runtime manifest")
    scenario = bundle.scenario.data
    execution = scenario["execution"]
    if execution["target_environment"] != "simulation":
        raise VerificationError("v0.5 verification is qualified only for simulation")
    result_id = str(scenario["scenario_id"])
    observe_clock = execution["time_mode"] != "hardware_realtime"
    observer = observer_factory(scenario["expected_ros_graph"], observe_clock=observe_clock)
    started_at = utc_now()
    measurement_started_ns = 0
    measurement_finished_ns = 0
    last_snapshot = None
    try:
        readiness = wait_for_readiness(
            scenario["expected_ros_graph"],
            observer,
            timeout_sec=float(scenario["timeouts"]["graph_ready_sec"]),
            stable_for_sec=float(scenario["timeouts"]["stable_for_sec"]),
            poll_interval_sec=poll_interval_sec,
            now_ns=now_ns,
            sleep_fn=sleep_fn,
        )
        measurement_started_ns = now_ns()
        deadline_ns = measurement_started_ns + int(
            float(scenario["timeouts"]["execution_sec"]) * 1_000_000_000
        )
        last_snapshot = readiness.snapshot
        while now_ns() < deadline_ns:
            last_snapshot = observer.snapshot()
            remaining_sec = max(0.0, (deadline_ns - now_ns()) / 1_000_000_000)
            sleep_fn(min(poll_interval_sec, remaining_sec))
        measurement_finished_ns = now_ns()
        raw_clock_samples = tuple(
            sample
            for sample in observer.clock_samples
            if sample.observed_at_ns >= measurement_started_ns
        )
    finally:
        observer.close()

    assert last_snapshot is not None
    evidence = _wait_for_evidence(
        evidence_index_path,
        result_id=result_id,
        timeout_sec=float(scenario["timeouts"]["shutdown_sec"]),
        poll_interval_sec=poll_interval_sec,
        now_ns=now_ns,
        sleep_fn=sleep_fn,
    )
    if otel_metrics_path is not None:
        if metric_samples:
            raise VerificationError("provide metric_samples or otel_metrics_path, not both")
        metrics_path = Path(otel_metrics_path).expanduser().resolve()
        metric_link = evidence.local_files.get(metrics_path)
        if metric_link is None or metric_link["media_type"] != "application/json":
            raise VerificationError(
                "OTLP metrics must be a verified local application/json evidence segment"
            )
        metric_samples = load_otlp_json_metrics(metrics_path)
    readiness = ReadinessResult(
        snapshot=last_snapshot,
        first_ready_at_ns=readiness.first_ready_at_ns,
        stable_for_sec=readiness.stable_for_sec,
    )
    clock_samples = _enrich_clock_samples(
        str(execution["time_mode"]),
        raw_clock_samples,
        metric_samples,
    )
    timing = evaluate_timing(execution, scenario["time_policy"], clock_samples)
    assertions = evaluate_metric_assertions(scenario["assertions"], metric_samples)
    finished_at = utc_now()
    result = build_acceptance_result(
        result_id=result_id,
        bundle=bundle,
        readiness=readiness,
        timing=timing,
        assertions=assertions,
        started_at=started_at,
        finished_at=finished_at,
        monotonic_duration_sec=(measurement_finished_ns - measurement_started_ns) / 1_000_000_000,
        shutdown={
            "observer_detached": True,
            "recorders_closed": True,
            "evidence_index_finalized": True,
        },
        evidence_index=evidence,
    )
    destination = Path(output_dir).expanduser().resolve()
    result_path = write_result_json(result, destination / "acceptance-result.json")
    junit_path = write_junit_xml(result, destination / "junit.xml")
    return VerificationOutputs(result, result_path, junit_path)


__all__ = ["VerificationError", "VerificationOutputs", "explain_bundle", "run_verification"]

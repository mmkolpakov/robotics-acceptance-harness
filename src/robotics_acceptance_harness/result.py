from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from tempfile import mkstemp
from typing import Any

from junitparser import Error, Failure, JUnitXml, TestCase, TestSuite
from robotics_runtime_contracts import validate_document

from robotics_acceptance_harness.documents import DocumentBundle
from robotics_acceptance_harness.evidence import VerifiedEvidence
from robotics_acceptance_harness.metrics import AssertionEvaluation
from robotics_acceptance_harness.readiness import GraphSnapshot, ReadinessResult
from robotics_acceptance_harness.timing import TimingObservation


def _iso8601(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _workload_result(runtime: Mapping[str, Any]) -> dict[str, Any]:
    if runtime["schema_version"] == "runtime-manifest.v1":
        inference = runtime["inference"]
        return {
            "kind": "inference",
            "runtime_family": inference["runtime_family"],
            "actual_provider": inference["actual_provider"],
            "model_format": runtime["model"]["format"],
            "fallback_count": inference["fallback_count"],
        }
    workload = runtime["workload"]
    if workload["kind"] == "none":
        return {"kind": "none"}
    return {
        "kind": "inference",
        "runtime_family": workload["inference"]["runtime_family"],
        "actual_provider": workload["inference"]["actual_provider"],
        "model_format": workload["model"]["format"],
        "fallback_count": workload["inference"]["fallback_count"],
    }


def _observed_graph(readiness: ReadinessResult) -> dict[str, Any]:
    snapshot = readiness.snapshot
    return {
        "stable_for_sec": readiness.stable_for_sec,
        "topics": [
            {
                "name": name,
                "type": observation.types[0],
                "publishers": observation.publishers,
                "subscribers": observation.subscribers,
                "first_message_at_ns": observation.first_message_at_ns,
            }
            for name, observation in sorted(snapshot.topics.items())
            if observation.first_message_at_ns is not None
        ],
        "services": [
            {"name": name, "type": observation.types[0], "servers": observation.servers}
            for name, observation in sorted(snapshot.services.items())
        ],
        "actions": [
            {"name": name, "type": observation.types[0], "servers": observation.servers}
            for name, observation in sorted(snapshot.actions.items())
        ],
    }


def _lifecycle_states(snapshot: GraphSnapshot) -> list[dict[str, Any]]:
    return [
        {
            "node": name,
            "state": observation.state,
            "observed_at_ns": observation.observed_at_ns,
        }
        for name, observation in sorted(snapshot.lifecycle_nodes.items())
    ]


def _status(evaluations: Sequence[AssertionEvaluation]) -> str:
    statuses = {evaluation.status for evaluation in evaluations}
    if "error" in statuses:
        return "error"
    if "failed" in statuses:
        return "failed"
    return "passed"


def build_acceptance_result(
    *,
    result_id: str,
    bundle: DocumentBundle,
    readiness: ReadinessResult,
    timing: TimingObservation,
    assertions: Sequence[AssertionEvaluation],
    started_at: datetime,
    finished_at: datetime,
    monotonic_duration_sec: float,
    shutdown: Mapping[str, bool],
    evidence: Sequence[Mapping[str, Any]] = (),
    evidence_index: VerifiedEvidence | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Build and validate one acceptance-result.v2 document."""

    if bundle.runtime is None:
        raise ValueError("acceptance-result.v2 requires a runtime manifest")
    if evidence_index is not None:
        if evidence:
            raise ValueError("provide evidence or evidence_index, not both")
        if evidence_index.index.data["run_id"] != result_id:
            raise ValueError("evidence index run_id must equal result_id")
        evidence = evidence_index.links
    result: dict[str, Any] = {
        "schema_version": "acceptance-result.v2",
        "result_id": result_id,
        "scenario_sha256": bundle.scenario.sha256,
        "runtime_manifest_sha256": bundle.runtime.sha256,
        "started_at": _iso8601(started_at),
        "finished_at": _iso8601(finished_at),
        "monotonic_duration_sec": monotonic_duration_sec,
        "status": status or _status(assertions),
        "assertion_results": [
            {
                "assertion_id": evaluation.assertion_id,
                "status": evaluation.status,
                "observed_value": evaluation.observed_value,
                "unit": evaluation.unit,
                **({"message": evaluation.message} if evaluation.message else {}),
            }
            for evaluation in assertions
        ],
        "observed_ros_graph": _observed_graph(readiness),
        "execution": {
            field: bundle.scenario.data["execution"][field]
            for field in (
                "target_environment",
                "data_source",
                "plant_backend",
                "time_mode",
                "data_plane_profile",
            )
        },
        "workload": _workload_result(bundle.runtime.data),
        "lifecycle_states": _lifecycle_states(readiness.snapshot),
        "clock_observation": {
            "monotonic": timing.monotonic,
            "offset_ms": timing.offset_ms,
            "drift_ppm": timing.drift_ppm,
            "real_time_factor": timing.real_time_factor,
            "deadline_miss_ratio": timing.deadline_miss_ratio,
        },
        "shutdown": dict(shutdown),
        "evidence": [dict(item) for item in evidence],
    }
    if bundle.model is not None:
        result["model_manifest_sha256"] = bundle.model.sha256
    if bundle.dataset is not None:
        result["dataset_manifest_sha256"] = bundle.dataset.sha256
    if bundle.permit is not None:
        result["permit_sha256"] = bundle.permit.sha256
    validate_document(result)
    return result


def _temporary_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    return Path(name)


def write_result_json(result: Mapping[str, Any], path: str | Path) -> Path:
    """Validate and atomically write an acceptance result as canonical JSON."""

    validate_document(result)
    destination = Path(path).expanduser().resolve()
    temporary_path = _temporary_path(destination)
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as temporary:
            json.dump(result, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination


def write_junit_xml(result: Mapping[str, Any], path: str | Path) -> Path:
    """Write assertion outcomes in standard JUnit XML using junitparser."""

    validate_document(result)
    suite = TestSuite("robotics-acceptance")
    suite.add_property("scenario_sha256", result["scenario_sha256"])
    suite.add_property("runtime_manifest_sha256", result["runtime_manifest_sha256"])
    assertion_results = result["assertion_results"] or [
        {
            "assertion_id": "acceptance",
            "status": result["status"],
            "message": "",
        }
    ]
    for assertion in assertion_results:
        case = TestCase(assertion["assertion_id"], classname="robotics.acceptance")
        message = assertion.get("message", "")
        if assertion["status"] == "failed":
            case.result = [Failure(message or "acceptance assertion failed")]
        elif assertion["status"] == "error":
            case.result = [Error(message or "acceptance assertion error")]
        suite.add_testcase(case)

    destination = Path(path).expanduser().resolve()
    temporary_path = _temporary_path(destination)
    try:
        xml = JUnitXml()
        xml.add_testsuite(suite)
        xml.write(temporary_path, pretty=True)
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination


__all__ = ["build_acceptance_result", "write_junit_xml", "write_result_json"]

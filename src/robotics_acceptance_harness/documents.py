from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import yaml
from robotics_runtime_contracts import validate_document

from robotics_acceptance_harness.authorization import evaluate_physical_authorization


class BundleValidationError(ValueError):
    """Raised when individually valid execution documents contradict each other."""

    def __init__(self, json_path: str, message: str) -> None:
        self.json_path = json_path
        self.validation_message = message
        super().__init__(f"{json_path}: {message}")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    path: Path
    data: Mapping[str, Any]
    sha256: str

    @property
    def schema_version(self) -> str:
        return str(self.data["schema_version"])


@dataclass(frozen=True, slots=True)
class DocumentBundle:
    scenario: LoadedDocument
    runtime: LoadedDocument | None = None
    model: LoadedDocument | None = None
    dataset: LoadedDocument | None = None
    permit: LoadedDocument | None = None
    verification: LoadedDocument | None = None


def _read_mapping(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise BundleValidationError("$", f"cannot read {path}: {error}") from error
    try:
        value = yaml.safe_load(raw)
    except yaml.YAMLError as error:
        raise BundleValidationError("$", f"cannot parse {path}: {error}") from error
    if not isinstance(value, dict):
        raise BundleValidationError("$", f"{path} must contain a JSON or YAML mapping")
    return raw, value


def load_document(
    path: str | Path,
    *,
    expected_schemas: set[str] | None = None,
    extension_schemas: Mapping[str, bytes | str] | None = None,
) -> LoadedDocument:
    """Load, validate, hash, and freeze one contract document."""

    resolved_path = Path(path).expanduser().resolve()
    raw, value = _read_mapping(resolved_path)
    schema_version = value.get("schema_version")
    if expected_schemas is not None and schema_version not in expected_schemas:
        expected = ", ".join(sorted(expected_schemas))
        raise BundleValidationError(
            "$.schema_version",
            f"expected one of {expected}; received {schema_version!r}",
        )
    try:
        validate_document(value, extension_schemas=extension_schemas)
    except ValueError as error:
        raise BundleValidationError("$", f"invalid {resolved_path}: {error}") from error
    return LoadedDocument(
        path=resolved_path,
        data=_freeze(value),
        sha256=sha256(raw).hexdigest(),
    )


def _require_equal(path: str, expected: Any, actual: Any) -> None:
    if expected != actual:
        raise BundleValidationError(path, f"expected {expected!r}; received {actual!r}")


def _runtime_workload(runtime: Mapping[str, Any]) -> Mapping[str, Any]:
    if runtime["schema_version"] == "runtime-manifest.v1":
        return MappingProxyType(
            {
                "kind": "inference",
                "model": runtime["model"],
                "inference": runtime["inference"],
                "accelerator": runtime["accelerator"],
            }
        )
    return cast(Mapping[str, Any], runtime["workload"])


def _validate_execution_alignment(
    scenario: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> None:
    scenario_execution = scenario["execution"]
    runtime_execution = runtime["execution"]
    for field in (
        "target_environment",
        "data_source",
        "plant_backend",
        "time_mode",
        "data_plane_profile",
    ):
        _require_equal(
            f"$.runtime.execution.{field}",
            scenario_execution[field],
            runtime_execution[field],
        )
    _require_equal(
        "$.runtime.security.profile",
        scenario_execution["security_profile"],
        runtime["security"]["profile"],
    )


def _validate_model_alignment(
    scenario: Mapping[str, Any],
    runtime: Mapping[str, Any],
    model: LoadedDocument | None,
) -> None:
    declared_digest = scenario.get("model_manifest_sha256")
    workload = _runtime_workload(runtime)
    if declared_digest is None:
        if workload["kind"] == "inference":
            raise BundleValidationError(
                "$.scenario.model_manifest_sha256",
                "inference workload requires a declared model manifest",
            )
        if model is not None:
            raise BundleValidationError("$.model", "model document was not requested by scenario")
        return

    if model is None:
        raise BundleValidationError("$.model", "scenario requires a model manifest")
    _require_equal("$.model.sha256", declared_digest, model.sha256)
    if workload["kind"] != "inference":
        raise BundleValidationError(
            "$.runtime.workload.kind",
            "scenario declares a model but runtime reports no inference workload",
        )
    _require_equal(
        "$.runtime.workload.model.manifest_sha256",
        model.sha256,
        workload["model"]["manifest_sha256"],
    )
    _require_equal(
        "$.runtime.workload.model.artifact_sha256",
        model.data["target"]["sha256"],
        workload["model"]["artifact_sha256"],
    )
    _require_equal(
        "$.runtime.workload.model.format",
        model.data["target"]["format"],
        workload["model"]["format"],
    )
    _require_equal(
        "$.runtime.workload.inference.actual_provider",
        model.data["target"]["execution_provider"],
        workload["inference"]["actual_provider"],
    )


def _validate_dataset_alignment(
    scenario: Mapping[str, Any],
    dataset: LoadedDocument | None,
) -> None:
    declared_digest = scenario.get("dataset_manifest_sha256")
    if declared_digest is None:
        if dataset is not None:
            raise BundleValidationError("$.dataset", "dataset was not requested by scenario")
        return
    if dataset is None:
        raise BundleValidationError("$.dataset", "scenario requires a dataset manifest")
    _require_equal("$.dataset.sha256", declared_digest, dataset.sha256)


def _validate_permit_alignment(
    scenario_document: LoadedDocument,
    runtime: Mapping[str, Any],
    permit: LoadedDocument | None,
    now: datetime,
) -> None:
    scenario = scenario_document.data
    target_environment = scenario["execution"]["target_environment"]
    if target_environment == "simulation":
        if permit is not None:
            raise BundleValidationError("$.permit", "simulation must not carry a hardware permit")
        return
    if permit is None:
        raise BundleValidationError(
            "$.permit",
            f"{target_environment} requires an execution permit",
        )

    _require_equal(
        "$.permit.scenario_sha256",
        scenario_document.sha256,
        permit.data["scenario_sha256"],
    )
    _require_equal(
        "$.permit.image_digest",
        runtime["oci_image"]["digest"],
        permit.data["image_digest"],
    )
    _require_equal(
        "$.permit.target.environment",
        target_environment,
        permit.data["target"]["environment"],
    )
    runtime_target_ids = {target["target_id"] for target in runtime["physical_targets"]}
    if permit.data["target"]["target_id"] not in runtime_target_ids:
        raise BundleValidationError(
            "$.permit.target.target_id",
            "permit target is absent from runtime physical_targets",
        )

    issued_at = datetime.fromisoformat(str(permit.data["issued_at"]).replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(str(permit.data["expires_at"]).replace("Z", "+00:00"))
    if not issued_at <= now < expires_at:
        raise BundleValidationError(
            "$.permit.expires_at",
            "permit is not active at verification time",
        )

    scenario_scope = set(scenario["execution"]["hardware_scope"])
    if not scenario_scope.issubset(set(permit.data["hardware_scope"])):
        raise BundleValidationError(
            "$.permit.hardware_scope",
            "does not cover scenario hardware_scope",
        )
    _require_equal(
        "$.permit.allowed_physical_effect",
        scenario["execution"]["physical_effect"],
        permit.data["allowed_physical_effect"],
    )


def load_bundle(
    scenario_path: str | Path,
    *,
    runtime_path: str | Path | None = None,
    model_path: str | Path | None = None,
    dataset_path: str | Path | None = None,
    permit_path: str | Path | None = None,
    verification_path: str | Path | None = None,
    extension_schemas: Mapping[str, bytes | str] | None = None,
    now: datetime | None = None,
) -> DocumentBundle:
    """Load and cross-check all documents required by one acceptance execution."""

    scenario = load_document(
        scenario_path,
        expected_schemas={
            "acceptance-scenario.v1",
            "acceptance-scenario.v2",
            "acceptance-scenario.v3",
        },
        extension_schemas=extension_schemas,
    )
    if scenario.schema_version == "acceptance-scenario.v1":
        if any(
            path is not None
            for path in (runtime_path, model_path, dataset_path, permit_path, verification_path)
        ):
            raise BundleValidationError("$", "v1 scenario accepts no execution manifests")
        return DocumentBundle(scenario=scenario)

    if runtime_path is None:
        raise BundleValidationError(
            "$.runtime",
            f"{scenario.schema_version} requires a runtime manifest",
        )
    runtime_schemas = (
        {"runtime-manifest.v3"}
        if scenario.schema_version == "acceptance-scenario.v3"
        else {"runtime-manifest.v1", "runtime-manifest.v2"}
    )
    runtime = load_document(
        runtime_path,
        expected_schemas=runtime_schemas,
    )
    model = (
        load_document(model_path, expected_schemas={"model-artifact-manifest.v1"})
        if model_path is not None
        else None
    )
    dataset = (
        load_document(dataset_path, expected_schemas={"dataset-manifest.v1"})
        if dataset_path is not None
        else None
    )
    permit_schemas = (
        {"execution-permit.v2"}
        if scenario.schema_version == "acceptance-scenario.v3"
        else {"execution-permit.v1"}
    )
    permit = (
        load_document(permit_path, expected_schemas=permit_schemas)
        if permit_path is not None
        else None
    )
    verification = (
        load_document(
            verification_path,
            expected_schemas={"execution-verification.v1"},
        )
        if verification_path is not None
        else None
    )

    _validate_execution_alignment(scenario.data, runtime.data)
    _validate_model_alignment(scenario.data, runtime.data, model)
    _validate_dataset_alignment(scenario.data, dataset)
    checked_at = now or datetime.now(UTC)
    if scenario.schema_version == "acceptance-scenario.v3":
        issues = evaluate_physical_authorization(
            scenario=scenario.data,
            scenario_sha256=scenario.sha256,
            runtime=runtime.data,
            permit=permit.data if permit is not None else None,
            permit_sha256=permit.sha256 if permit is not None else None,
            permit_path=permit.path if permit is not None else None,
            verification=verification.data if verification is not None else None,
            verification_sha256=verification.sha256 if verification is not None else None,
            verification_path=verification.path if verification is not None else None,
            now=checked_at,
        )
        if issues:
            raise BundleValidationError(issues[0].json_path, issues[0].message)
    else:
        if verification is not None:
            raise BundleValidationError(
                "$.verification",
                "acceptance-scenario.v2 does not accept execution verification",
            )
        _validate_permit_alignment(
            scenario,
            runtime.data,
            permit,
            checked_at,
        )
    return DocumentBundle(
        scenario=scenario,
        runtime=runtime,
        model=model,
        dataset=dataset,
        permit=permit,
        verification=verification,
    )


__all__ = [
    "BundleValidationError",
    "DocumentBundle",
    "LoadedDocument",
    "load_bundle",
    "load_document",
]

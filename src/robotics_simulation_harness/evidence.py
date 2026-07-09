from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str, default: str = "0.0.0") -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return default


def make_evidence(
    *,
    run_id: str,
    scenario_path: Path,
    scenario: dict[str, Any],
    result: str,
    checks: list[dict[str, str]],
    ros_domain_id: int,
    stack_lock_sha256: str,
    infra_image_digest: str,
    signed: bool = False,
    signer_identity: str | None = None,
    business_repo: dict[str, Any] | None = None,
    extra_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scenario_hash = file_sha256(scenario_path)
    artifacts = [
        {
            "name": "resolved-scenario",
            "uri": str(scenario_path),
            "sha256": scenario_hash,
            "bytes": scenario_path.stat().st_size,
            "retention": scenario["recording"]["retention"],
        }
    ]
    if extra_artifacts:
        artifacts.extend(extra_artifacts)

    payload: dict[str, Any] = {
        "schema_version": "evidence-manifest.v1",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "result": result,
        "ros_domain_id": ros_domain_id,
        "stack_lock_sha256": stack_lock_sha256,
        "harness_version": package_version("robotics-simulation-harness", "0.2.0"),
        "contracts_version": package_version("robotics-runtime-contracts", "0.2.0"),
        "infra_image_digest": infra_image_digest,
        "signed": signed,
        "scenario": {
            "scenario_id": scenario["scenario_id"],
            "resolved_manifest_sha256": scenario_hash,
        },
        "artifacts": artifacts,
        "checks": checks,
        "business_repo": business_repo,
    }
    if signer_identity is not None:
        payload["signer_identity"] = signer_identity
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

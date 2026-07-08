from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_evidence(
    *,
    run_id: str,
    scenario_path: Path,
    scenario: dict[str, Any],
    result: str,
    checks: list[dict[str, str]],
) -> dict[str, Any]:
    scenario_hash = file_sha256(scenario_path)
    return {
        "schema_version": "evidence-manifest.v1",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "result": result,
        "scenario": {
            "scenario_id": scenario["scenario_id"],
            "resolved_manifest_sha256": scenario_hash,
        },
        "artifacts": [
            {
                "name": "resolved-scenario",
                "uri": str(scenario_path),
                "sha256": scenario_hash,
                "bytes": scenario_path.stat().st_size,
                "retention": scenario["recording"]["retention"],
            }
        ],
        "checks": checks,
    }

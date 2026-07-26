from __future__ import annotations

from pathlib import Path

from robotics_acceptance_harness.documents import (
    BundleValidationError,
    LoadedDocument,
    load_document,
)


def load_run_context(
    path: str | Path,
    *,
    run_id: str,
    domain_id: str,
    scenario_id: str,
    scenario_sha256: str,
) -> LoadedDocument:
    """Load an immutable run context and bind it to one domain execution."""

    context = load_document(path, expected_schemas={"acceptance-run.v1"})
    if context.data["run_id"] != run_id:
        raise BundleValidationError("$.run_id", "run context does not match --run-id")
    if context.data["scenario_id"] != scenario_id:
        raise BundleValidationError("$.scenario_id", "run context does not match the scenario")
    if context.data["scenario_sha256"] != scenario_sha256:
        raise BundleValidationError(
            "$.scenario_sha256",
            "run context does not match the scenario digest",
        )
    domains = {item["domain_id"] for item in context.data["domains"]}
    if domain_id not in domains:
        raise BundleValidationError(
            "$.domains",
            f"domain {domain_id!r} is not registered in the run context",
        )
    return context


__all__ = ["load_run_context"]

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


class SchemaValidationError(ValueError):
    pass


def _candidate_schema_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_dir = os.environ.get("ROBOTICS_CONTRACTS_SCHEMA_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    env_root = os.environ.get("ROBOTICS_CONTRACTS_ROOT")
    if env_root:
        dirs.append(Path(env_root) / "schemas")
        dirs.append(Path(env_root) / "src" / "robotics_runtime_contracts" / "schemas")
    try:
        from robotics_runtime_contracts import schema_dir as contracts_schema_dir

        dirs.append(Path(contracts_schema_dir()))
    except Exception:  # noqa: BLE001 - optional dependency path
        pass
    local_vendor = Path(__file__).resolve().parents[2] / "vendor" / "contracts-schemas"
    dirs.append(local_vendor)
    local = Path(__file__).resolve().parents[3] / "robotics-runtime-contracts" / "schemas"
    dirs.append(local)
    return dirs


@lru_cache(maxsize=1)
def _load_registry() -> tuple[dict[str, dict[str, Any]], Registry]:
    schema_root = next((path for path in _candidate_schema_dirs() if path.is_dir()), None)
    if schema_root is None:
        raise SchemaValidationError(
            "robotics-runtime-contracts schemas not found; install the package "
            "or set ROBOTICS_CONTRACTS_SCHEMA_DIR"
        )
    schemas: dict[str, dict[str, Any]] = {}
    pairs: list[tuple[str, Resource]] = []
    for path in sorted(schema_root.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        key = path.name.replace(".v1.schema.json", "")
        schemas[key] = schema
        resource = Resource.from_contents(schema)
        pairs.append((schema["$id"], resource))
        pairs.append((path.name, resource))
    return schemas, Registry().with_resources(pairs)


def validate_document(schema_name: str, document: dict[str, Any]) -> None:
    schemas, registry = _load_registry()
    if schema_name not in schemas:
        raise SchemaValidationError(f"unknown schema: {schema_name}")
    validator = Draft202012Validator(schemas[schema_name], registry=registry)
    errors = sorted(validator.iter_errors(document), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        path = "/".join(str(part) for part in first.path) or "/"
        raise SchemaValidationError(f"{schema_name} invalid at {path}: {first.message}")


def validate_scenario(document: dict[str, Any]) -> None:
    validate_document("scenario-manifest", document)
    simulation = document["simulation"]
    if simulation["wall_timeout_sec"] <= simulation["duration_sec"]:
        raise SchemaValidationError("wall_timeout_sec must be greater than duration_sec")


def validate_composition(document: dict[str, Any]) -> None:
    validate_document("scenario-composition-manifest", document)


def validate_evidence(document: dict[str, Any]) -> None:
    validate_document("evidence-manifest", document)

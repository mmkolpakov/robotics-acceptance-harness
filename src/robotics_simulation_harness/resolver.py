from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .yaml_io import read_yaml_or_json


@dataclass(frozen=True)
class TraceEntry:
    source: str
    path: str
    operation: str
    old: Any
    new: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "path": self.path,
            "operation": self.operation,
            "old": self.old,
            "new": self.new,
        }


def merge_patch(base: Any, patch: Any, source: str, trace: list[TraceEntry], path: str = "") -> Any:
    if patch is None:
        trace.append(TraceEntry(source, path or "/", "remove", base, None))
        return None
    if not isinstance(base, dict) or not isinstance(patch, dict):
        if base != patch:
            trace.append(TraceEntry(source, path or "/", "replace", base, patch))
        return patch

    merged = dict(base)
    for key, value in patch.items():
        child_path = f"{path}/{key}" if path else f"/{key}"
        if value is None:
            old = merged.pop(key, None)
            trace.append(TraceEntry(source, child_path, "remove", old, None))
            continue
        if key in merged:
            merged[key] = merge_patch(merged[key], value, source, trace, child_path)
        else:
            merged[key] = value
            trace.append(TraceEntry(source, child_path, "add", None, value))
    return merged


def resolve_composition(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    composition = read_yaml_or_json(path)
    root = path.parent
    base_path = (root / composition["base"]["path"]).resolve()
    resolved = read_yaml_or_json(base_path)
    trace: list[TraceEntry] = [
        TraceEntry(str(base_path), "/", "base", None, resolved),
    ]

    for component in composition.get("components", []):
        component_path = (root / component["path"]).resolve()
        resolved = merge_patch(
            resolved,
            read_yaml_or_json(component_path),
            str(component_path),
            trace,
        )

    for overlay in composition.get("overlays", []):
        if overlay["mode"] != "yaml_merge_patch":
            raise ValueError("Only yaml_merge_patch overlays are supported in v0.1")
        overlay_path = (root / overlay["path"]).resolve()
        resolved = merge_patch(
            resolved,
            read_yaml_or_json(overlay_path),
            str(overlay_path),
            trace,
        )

    return resolved, [entry.as_dict() for entry in trace]

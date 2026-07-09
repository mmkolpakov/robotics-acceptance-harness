from __future__ import annotations

from pathlib import Path

from robotics_simulation_harness.resolver import resolve_composition

ROOT = Path(__file__).resolve().parents[1]


def test_resolve_composition_records_trace() -> None:
    resolved, trace = resolve_composition(ROOT / "examples" / "generic" / "composition.yaml")

    assert resolved["simulation"]["duration_sec"] == 3
    assert resolved["simulation"]["wall_timeout_sec"] == 20
    assert resolved["recording"]["retention"]["mode"] == "always"
    assert any(entry["path"] == "/simulation/duration_sec" for entry in trace)
    assert any(entry["source"].endswith("short-run.yaml") for entry in trace)

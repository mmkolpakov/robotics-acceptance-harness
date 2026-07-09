from __future__ import annotations

from pathlib import Path

import pytest

from robotics_simulation_harness.resolver import resolve_composition
from robotics_simulation_harness.schemas import SchemaValidationError, validate_scenario

ROOT = Path(__file__).resolve().parents[1]


def test_resolve_composition_records_trace() -> None:
    resolved, trace = resolve_composition(ROOT / "examples" / "generic" / "composition.yaml")

    assert resolved["simulation"]["duration_sec"] == 3
    assert resolved["simulation"]["wall_timeout_sec"] == 20
    assert resolved["recording"]["retention"]["mode"] == "always"
    assert any(entry["path"] == "/simulation/duration_sec" for entry in trace)
    assert any(entry["source"].endswith("short-run.yaml") for entry in trace)


def test_overlay_list_replace_is_traced_as_list_replaced() -> None:
    """A list-valued overlay key must produce a `list_replaced` trace entry,
    distinct from a scalar `replace`, so authors can see that the whole base
    array (not just one element) was dropped.
    """
    resolved, trace = resolve_composition(
        ROOT / "examples" / "generic" / "composition-drop-clock.yaml"
    )

    list_replacements = [entry for entry in trace if entry["operation"] == "list_replaced"]
    assert list_replacements, trace
    topics_replacement = next(
        entry for entry in list_replacements if entry["path"] == "/expected_ros_graph/topics"
    )
    assert {topic["name"] for topic in topics_replacement["old"]} == {"/clock"}
    assert {topic["name"] for topic in topics_replacement["new"]} == {"/camera/image"}

    # The overlay silently dropped `/clock` from `topics` while
    # `require_clock` is still `true`: this must fail schema validation
    # fail-closed, rather than resolving into a scenario that can never
    # observe a real graph_ready pass.
    assert resolved["expected_ros_graph"]["require_clock"] is True
    with pytest.raises(SchemaValidationError):
        validate_scenario(resolved)

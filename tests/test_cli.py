from __future__ import annotations

import json
from pathlib import Path

from robotics_simulation_harness.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_cli_resolve_and_run(tmp_path: Path, monkeypatch) -> None:
    resolved = tmp_path / "resolved.json"
    trace = tmp_path / "trace.json"
    evidence = tmp_path / "evidence.json"

    monkeypatch.setattr(
        "sys.argv",
        [
            "robotics-harness",
            "scenario",
            "resolve",
            "--composition",
            str(ROOT / "examples" / "generic" / "composition.yaml"),
            "--output",
            str(resolved),
            "--trace",
            str(trace),
        ],
    )
    assert main() == 0
    assert resolved.exists()
    assert trace.exists()

    monkeypatch.setattr(
        "sys.argv",
        [
            "robotics-harness",
            "run",
            "--scenario",
            str(resolved),
            "--evidence",
            str(evidence),
            "--dry-run",
        ],
    )
    assert main() == 0
    data = json.loads(evidence.read_text(encoding="utf-8"))
    assert data["result"] == "pass"
    assert data["scenario"]["scenario_id"] == "generic.empty_world"

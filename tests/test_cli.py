from __future__ import annotations

import json
from pathlib import Path

from robotics_acceptance_harness.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "simulation"


def test_explain_validates_bundle_without_ros(capsys) -> None:
    exit_code = main(
        [
            "explain",
            "--scenario",
            str(FIXTURES / "scenario.yaml"),
            "--runtime",
            str(FIXTURES / "runtime.yaml"),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["policy"] == "accepted-simulation"
    assert output["workload_kind"] == "none"


def test_explain_rejects_invalid_extension_argument(capsys) -> None:
    exit_code = main(
        [
            "explain",
            "--scenario",
            str(FIXTURES / "scenario.yaml"),
            "--runtime",
            str(FIXTURES / "runtime.yaml"),
            "--extension-schema",
            "invalid",
        ]
    )

    assert exit_code == 2
    assert "invalid --extension-schema" in capsys.readouterr().err

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    assert "$.data_plane_policy.max_loss_ratio" in output["unevaluated"]
    assert "$.evidence_policy.topics" in output["unevaluated"]


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


def test_verify_requires_run_id(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "verify",
                "--scenario",
                str(FIXTURES / "scenario.yaml"),
                "--runtime",
                str(FIXTURES / "runtime.yaml"),
                "--evidence-index",
                "evidence-index.yaml",
                "--output",
                "output",
            ]
        )

    assert caught.value.code == 2
    assert "--run-id" in capsys.readouterr().err


def test_v1_verify_does_not_require_domain_or_run_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_run_verification(**arguments: object) -> SimpleNamespace:
        captured.update(arguments)
        return SimpleNamespace(
            result={"status": "passed"},
            result_path=tmp_path / "acceptance-result.json",
            junit_path=tmp_path / "junit.xml",
        )

    monkeypatch.setattr(
        "robotics_acceptance_harness.cli.run_verification",
        fake_run_verification,
    )

    exit_code = main(
        [
            "verify",
            "--scenario",
            str(FIXTURES / "scenario.yaml"),
            "--runtime",
            str(FIXTURES / "runtime.yaml"),
            "--run-id",
            "run-6ba7b810-9dad-41d1-80b4-00c04fd430c8",
            "--evidence-index",
            "evidence-index.yaml",
            "--output",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert captured["domain_id"] is None
    assert captured["run_context_path"] is None
    assert json.loads(capsys.readouterr().out)["status"] == "passed"

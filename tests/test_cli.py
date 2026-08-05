from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from robotics_acceptance_harness.cli import main
from tests.support import write_extended_scenario

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
    assert output["unevaluated"] == []


def test_create_run_derives_identity_and_digest_from_scenario(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_id = "run-6ba7b810-9dad-41d1-80b4-00c04fd430c8"
    output_path = tmp_path / "acceptance-run.json"

    exit_code = main(
        [
            "create-run",
            "--scenario",
            str(FIXTURES / "scenario.yaml"),
            "--output",
            str(output_path),
            "--domain",
            "primary=observer",
            "--time-authority",
            "sim_clock",
            "--time-source",
            "gazebo-clock",
            "--run-id",
            run_id,
        ]
    )

    document = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert capsys.readouterr().out.strip() == run_id
    assert document["scenario_id"] == "org.example.physics-smoke"
    assert document["scenario_sha256"]
    assert document["domains"] == [{"domain_id": "primary", "role": "observer"}]


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


def test_explain_loads_extension_schema_by_canonical_uri(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scenario, schema, uri = write_extended_scenario(tmp_path, FIXTURES / "scenario.yaml")

    exit_code = main(
        [
            "explain",
            "--scenario",
            str(scenario),
            "--runtime",
            str(FIXTURES / "runtime.yaml"),
            "--extension-schema",
            f"{uri}={schema}",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["policy"] == "accepted-simulation"


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


def test_verify_forwards_canonical_run_inputs(
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
            "--domain-id",
            "camera-domain",
            "--run-context",
            "acceptance-run.yaml",
            "--evidence-index",
            "evidence-index.yaml",
            "--otel-metrics",
            "metrics.otlp.json",
            "--measurement-complete",
            str(tmp_path / "measurement-complete"),
            "--output",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert captured["domain_id"] == "camera-domain"
    assert captured["run_context_path"] == "acceptance-run.yaml"
    assert captured["otel_metrics_path"] == "metrics.otlp.json"
    assert captured["measurement_complete_path"] == str(tmp_path / "measurement-complete")
    assert json.loads(capsys.readouterr().out)["status"] == "passed"


def test_aggregate_forwards_transport_qualification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}
    output = tmp_path / "acceptance-aggregate.json"

    def fake_aggregate_results(**arguments: object) -> Path:
        captured.update(arguments)
        output.write_text(
            json.dumps(
                {
                    "per_domain_aggregate": "passed",
                    "cross_domain_e2e": {"status": "failed"},
                }
            ),
            encoding="utf-8",
        )
        return output

    monkeypatch.setattr(
        "robotics_acceptance_harness.cli.aggregate_results",
        fake_aggregate_results,
    )

    exit_code = main(
        [
            "aggregate",
            "--run-context",
            "acceptance-run.json",
            "--result",
            "domain-result.json",
            "--transport-qualification",
            "transport-qualification.json",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    assert captured["transport_qualification_path"] == "transport-qualification.json"
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_transport_evaluate_maps_domain_evidence_and_reports_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}
    output = tmp_path / "transport-qualification.json"

    def fake_evaluate_transport_qualification(**arguments: object) -> Path:
        captured.update(arguments)
        output.write_text(
            json.dumps({"verdict": {"status": "passed"}}),
            encoding="utf-8",
        )
        return output

    monkeypatch.setattr(
        "robotics_acceptance_harness.cli.evaluate_transport_qualification",
        fake_evaluate_transport_qualification,
    )

    exit_code = main(
        [
            "transport-evaluate",
            "--run-id",
            "run-6ba7b810-9dad-41d1-80b4-00c04fd430c8",
            "--causal-chain",
            "causal-chain.json",
            "--channel-contract",
            "channel.json",
            "--trace",
            "source=source-traces.json",
            "--trace",
            "target=target-traces.json",
            "--evidence-index",
            "source=source-evidence.json",
            "--evidence-index",
            "target=target-evidence.json",
            "--observation-output",
            str(tmp_path / "observations"),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert captured["trace_paths"] == {
        "source": "source-traces.json",
        "target": "target-traces.json",
    }
    assert captured["evidence_index_paths"] == {
        "source": "source-evidence.json",
        "target": "target-evidence.json",
    }
    assert json.loads(capsys.readouterr().out) == {
        "qualification": str(output),
        "status": "passed",
    }

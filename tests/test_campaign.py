from __future__ import annotations

import json
from pathlib import Path

import pytest

from robotics_acceptance_harness.campaign import aggregate_campaign
from robotics_acceptance_harness.documents import BundleValidationError
from tests.test_aggregate import base_aggregate, run_context, write_json

SCENARIO = Path(__file__).parent / "fixtures" / "simulation" / "scenario.yaml"


def test_campaign_aggregates_digest_linked_run_verdicts(tmp_path: Path) -> None:
    context = run_context(tmp_path)
    aggregate = base_aggregate(tmp_path, context)
    output = aggregate_campaign(
        scenario_path=SCENARIO,
        run_context_paths=(context,),
        aggregate_paths=(aggregate,),
        output_path=tmp_path / "campaign.json",
        minimum_passed_runs=1,
    )

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["schema_version"] == "campaign-summary.v1"
    assert document["verdict"]["status"] == "passed"
    assert document["scenario_sha256"]
    assert document["runs"][0]["acceptance_run_sha256"]
    assert document["runs"][0]["aggregate_sha256"]


def test_campaign_rejects_aggregate_for_another_run_context(tmp_path: Path) -> None:
    context = run_context(tmp_path)
    aggregate_path = base_aggregate(tmp_path, context)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["acceptance_run_sha256"] = "f" * 64
    write_json(aggregate_path, aggregate)

    with pytest.raises(BundleValidationError, match="another run context"):
        aggregate_campaign(
            scenario_path=SCENARIO,
            run_context_paths=(context,),
            aggregate_paths=(aggregate_path,),
            output_path=tmp_path / "campaign.json",
            minimum_passed_runs=1,
        )


def test_campaign_preserves_incomplete_as_the_policy_verdict(tmp_path: Path) -> None:
    context = run_context(tmp_path)
    aggregate_path = base_aggregate(tmp_path, context)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["per_domain_results"][0]["status"] = "incomplete"
    aggregate["per_domain_aggregate"] = "incomplete"
    write_json(aggregate_path, aggregate)

    output = aggregate_campaign(
        scenario_path=SCENARIO,
        run_context_paths=(context,),
        aggregate_paths=(aggregate_path,),
        output_path=tmp_path / "campaign.json",
        minimum_passed_runs=2,
    )

    assert json.loads(output.read_text(encoding="utf-8"))["verdict"]["status"] == "incomplete"

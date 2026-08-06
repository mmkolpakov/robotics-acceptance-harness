from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from robotics_acceptance_harness.evidence import EvidenceValidationError, load_evidence_index
from tests.support import evidence_index, local_evidence_segment


def _index(path: Path, *, digest: str | None = None, size: int | None = None) -> dict[str, object]:
    overrides = {
        key: value for key, value in (("sha256", digest), ("size_bytes", size)) if value is not None
    }
    return evidence_index(
        "org.example.physics-smoke-001",
        [local_evidence_segment(path, media_type="application/json", overrides=overrides)],
    )


def _write_index(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "evidence-index.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_verified_local_evidence_becomes_result_link(tmp_path: Path) -> None:
    segment = tmp_path / "run.json"
    segment.write_bytes(b"verified evidence")

    verified = load_evidence_index(
        _write_index(tmp_path, _index(segment)),
        expected_run_id="org.example.physics-smoke-001",
    )

    assert verified.links[0]["uri"] == segment.as_uri()
    assert segment.resolve() in verified.local_files
    assert "local_path" not in verified.links[0]
    assert "upload_status" not in verified.links[0]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("digest", "0" * 64, "sha256"),
        ("size", 1, "size_bytes"),
    ],
)
def test_tampered_local_evidence_is_rejected(
    tmp_path: Path,
    field: str,
    value: str | int,
    message: str,
) -> None:
    segment = tmp_path / "run.json"
    segment.write_bytes(b"verified evidence")
    options = {field: value}

    with pytest.raises(EvidenceValidationError, match=message):
        load_evidence_index(_write_index(tmp_path, _index(segment, **options)))


def test_missing_local_evidence_is_rejected(tmp_path: Path) -> None:
    segment = tmp_path / "run.json"
    segment.write_bytes(b"verified evidence")
    index = _write_index(tmp_path, _index(segment))
    segment.unlink()

    with pytest.raises(EvidenceValidationError, match="does not exist"):
        load_evidence_index(index)


def test_confirmed_versioned_s3_evidence_needs_no_network(tmp_path: Path) -> None:
    document = evidence_index(
        "org.example.physics-smoke-001",
        [
            {
                "uri": "s3://robotics-evidence/run.json",
                "version_id": "3LgExampleVersion",
                "media_type": "application/json",
                "sha256": "a" * 64,
                "size_bytes": 2048,
                "retention_class": "regression-30d",
                "segment_index": 0,
                "upload_status": "confirmed",
                "checksum_verified": True,
            }
        ],
        upload_mode="closed_segments_during_run",
    )

    verified = load_evidence_index(_write_index(tmp_path, document))

    assert verified.links[0]["version_id"] == "3LgExampleVersion"


def test_unconfirmed_s3_evidence_is_rejected(tmp_path: Path) -> None:
    document = evidence_index(
        "org.example.physics-smoke-001",
        [
            {
                "uri": "s3://robotics-evidence/run.json",
                "media_type": "application/json",
                "sha256": "a" * 64,
                "size_bytes": 2048,
                "retention_class": "regression-30d",
                "segment_index": 0,
                "upload_status": "local",
                "checksum_verified": False,
            }
        ],
    )

    with pytest.raises(EvidenceValidationError, match="invalid"):
        load_evidence_index(_write_index(tmp_path, document))


def test_run_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    segment = tmp_path / "run.json"
    segment.write_bytes(b"verified evidence")

    with pytest.raises(EvidenceValidationError, match="run_id"):
        load_evidence_index(
            _write_index(tmp_path, _index(segment)),
            expected_run_id="org.example.other-run",
        )


def test_scenario_v5_rejects_an_older_evidence_index(tmp_path: Path) -> None:
    segment = tmp_path / "run.json"
    segment.write_bytes(b"verified evidence")

    with pytest.raises(EvidenceValidationError, match="requires evidence-index.v3"):
        load_evidence_index(
            _write_index(tmp_path, _index(segment)),
            scenario_schema="acceptance-scenario.v5",
        )

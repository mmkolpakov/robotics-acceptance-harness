from __future__ import annotations

from hashlib import sha256
from os import name as os_name
from pathlib import Path

import pytest
import yaml

from robotics_acceptance_harness.evidence import EvidenceValidationError, load_evidence_index


def _index(path: Path, *, digest: str | None = None, size: int | None = None) -> dict[str, object]:
    content = path.read_bytes()
    local_path = path.as_posix()
    if os_name == "nt":
        local_path = f"/{local_path}"
    return {
        "schema_version": "evidence-index.v1",
        "run_id": "org.example.physics-smoke-001",
        "generated_at": "2026-07-11T12:01:00Z",
        "finalized": True,
        "segments": [
            {
                "uri": path.as_uri(),
                "local_path": local_path,
                "media_type": "application/mcap",
                "sha256": digest or sha256(content).hexdigest(),
                "size_bytes": len(content) if size is None else size,
                "retention_class": "pull-request-7d",
                "segment_index": 0,
                "upload_status": "local",
                "checksum_verified": True,
            }
        ],
    }


def _write_index(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "evidence-index.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_verified_local_evidence_becomes_result_link(tmp_path: Path) -> None:
    segment = tmp_path / "run.mcap"
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
    segment = tmp_path / "run.mcap"
    segment.write_bytes(b"verified evidence")
    options = {field: value}

    with pytest.raises(EvidenceValidationError, match=message):
        load_evidence_index(_write_index(tmp_path, _index(segment, **options)))


def test_missing_local_evidence_is_rejected(tmp_path: Path) -> None:
    segment = tmp_path / "run.mcap"
    segment.write_bytes(b"verified evidence")
    index = _write_index(tmp_path, _index(segment))
    segment.unlink()

    with pytest.raises(EvidenceValidationError, match="does not exist"):
        load_evidence_index(index)


def test_confirmed_versioned_s3_evidence_needs_no_network(tmp_path: Path) -> None:
    document = {
        "schema_version": "evidence-index.v1",
        "run_id": "org.example.physics-smoke-001",
        "generated_at": "2026-07-11T12:01:00Z",
        "finalized": True,
        "segments": [
            {
                "uri": "s3://robotics-evidence/run.mcap",
                "version_id": "3LgExampleVersion",
                "media_type": "application/mcap",
                "sha256": "a" * 64,
                "size_bytes": 2048,
                "retention_class": "regression-30d",
                "segment_index": 0,
                "upload_status": "confirmed",
                "checksum_verified": True,
            }
        ],
    }

    verified = load_evidence_index(_write_index(tmp_path, document))

    assert verified.links[0]["version_id"] == "3LgExampleVersion"


def test_unconfirmed_s3_evidence_is_rejected(tmp_path: Path) -> None:
    document = {
        "schema_version": "evidence-index.v1",
        "run_id": "org.example.physics-smoke-001",
        "generated_at": "2026-07-11T12:01:00Z",
        "finalized": True,
        "segments": [
            {
                "uri": "s3://robotics-evidence/run.mcap",
                "media_type": "application/mcap",
                "sha256": "a" * 64,
                "size_bytes": 2048,
                "retention_class": "regression-30d",
                "segment_index": 0,
                "upload_status": "local",
                "checksum_verified": False,
            }
        ],
    }

    with pytest.raises(EvidenceValidationError, match="invalid"):
        load_evidence_index(_write_index(tmp_path, document))


def test_run_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    segment = tmp_path / "run.mcap"
    segment.write_bytes(b"verified evidence")

    with pytest.raises(EvidenceValidationError, match="run_id"):
        load_evidence_index(
            _write_index(tmp_path, _index(segment)),
            expected_run_id="org.example.other-run",
        )

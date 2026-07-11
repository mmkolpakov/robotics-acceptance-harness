from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import file_digest
from os import name as os_name
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import unquote, urlsplit

from robotics_acceptance_harness.documents import (
    BundleValidationError,
    LoadedDocument,
    load_document,
)


class EvidenceValidationError(ValueError):
    """Raised when finalized evidence cannot be independently verified."""

    def __init__(self, json_path: str, message: str) -> None:
        self.json_path = json_path
        self.validation_message = message
        super().__init__(f"{json_path}: {message}")


@dataclass(frozen=True, slots=True)
class VerifiedEvidence:
    index: LoadedDocument
    links: tuple[Mapping[str, Any], ...]


def _platform_path(value: str) -> Path:
    if os_name == "nt" and len(value) > 3 and value[0] == "/" and value[2] == ":":
        value = value[1:]
    return Path(value)


def _local_link(segment: Mapping[str, Any], index: int) -> Mapping[str, Any]:
    path = _platform_path(str(segment["local_path"]))
    json_path = f"$.segments[{index}]"
    uri = urlsplit(str(segment["uri"]))
    if uri.scheme != "file" or uri.netloc not in {"", "localhost"}:
        raise EvidenceValidationError(
            f"{json_path}.uri",
            "local evidence requires a local file URI",
        )
    uri_path = _platform_path(unquote(uri.path))
    if uri_path.resolve() != path.resolve():
        raise EvidenceValidationError(
            f"{json_path}.local_path",
            f"does not identify file URI {segment['uri']}",
        )
    if not path.is_file():
        raise EvidenceValidationError(f"{json_path}.local_path", f"file does not exist: {path}")
    observed_size = path.stat().st_size
    if observed_size != segment["size_bytes"]:
        raise EvidenceValidationError(
            f"{json_path}.size_bytes",
            f"expected {segment['size_bytes']}; observed {observed_size}",
        )
    with path.open("rb") as stream:
        observed_digest = file_digest(stream, "sha256").hexdigest()
    if observed_digest != segment["sha256"]:
        raise EvidenceValidationError(
            f"{json_path}.sha256",
            f"expected {segment['sha256']}; observed {observed_digest}",
        )
    return _result_link(segment)


def _remote_link(segment: Mapping[str, Any], index: int) -> Mapping[str, Any]:
    json_path = f"$.segments[{index}]"
    if segment["upload_status"] != "confirmed" or not segment["checksum_verified"]:
        raise EvidenceValidationError(json_path, "remote evidence is not confirmed")
    if str(segment["uri"]).startswith("s3://") and not segment.get("version_id"):
        raise EvidenceValidationError(f"{json_path}.version_id", "S3 evidence has no version ID")
    return _result_link(segment)


def _result_link(segment: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = (
        "uri",
        "version_id",
        "media_type",
        "sha256",
        "size_bytes",
        "retention_class",
        "segment_index",
    )
    return MappingProxyType({field: segment[field] for field in fields if field in segment})


def load_evidence_index(
    path: str | Path,
    *,
    expected_run_id: str | None = None,
) -> VerifiedEvidence:
    """Validate a finalized index and verify every reusable evidence link."""

    try:
        document = load_document(path, expected_schemas={"evidence-index.v1"})
    except BundleValidationError as error:
        raise EvidenceValidationError(error.json_path, error.validation_message) from error
    if expected_run_id is not None and document.data["run_id"] != expected_run_id:
        raise EvidenceValidationError(
            "$.run_id",
            f"expected {expected_run_id!r}; received {document.data['run_id']!r}",
        )

    links: list[Mapping[str, Any]] = []
    for index, segment in enumerate(document.data["segments"]):
        if segment["upload_status"] == "local":
            links.append(_local_link(segment, index))
        else:
            links.append(_remote_link(segment, index))
    return VerifiedEvidence(document, tuple(links))


__all__ = ["EvidenceValidationError", "VerifiedEvidence", "load_evidence_index"]

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from google.protobuf.json_format import ParseDict
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)

from robotics_acceptance_harness.metrics import MetricSample


class MetricInputError(ValueError):
    """Raised when an OTLP JSON file cannot be interpreted as metric samples."""


def _number_value(point: Any) -> float | None:
    value_kind = point.WhichOneof("value")
    if value_kind == "as_double":
        return float(point.as_double)
    if value_kind == "as_int":
        return float(point.as_int)
    return None


def load_otlp_json_metrics(path: str | Path) -> tuple[MetricSample, ...]:
    """Read newline-delimited OTLP JSON emitted by the Collector file exporter."""

    source = Path(path).expanduser().resolve()
    samples: list[MetricSample] = []
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise MetricInputError(f"cannot read {source}: {error}") from error

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            request = ParseDict(payload, ExportMetricsServiceRequest())
        except (json.JSONDecodeError, ValueError) as error:
            raise MetricInputError(
                f"invalid OTLP JSON at {source}:{line_number}: {error}"
            ) from error

        for resource_metrics in request.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    data_kind = metric.WhichOneof("data")
                    if data_kind not in {"gauge", "sum"}:
                        continue
                    data = getattr(metric, data_kind)
                    for point in data.data_points:
                        value = _number_value(point)
                        if value is None:
                            continue
                        samples.append(
                            MetricSample(
                                name=metric.name,
                                value=value,
                                unit=metric.unit,
                                observed_at_ns=int(point.time_unix_nano),
                            )
                        )
    return tuple(samples)


__all__ = ["MetricInputError", "load_otlp_json_metrics"]

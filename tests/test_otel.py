from __future__ import annotations

import json
from pathlib import Path

import pytest

from robotics_acceptance_harness.otel import MetricInputError, load_otlp_json_metrics


def test_loads_standard_otlp_json_number_points(tmp_path: Path) -> None:
    payload = {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "robotics.clock.sync_protocol",
                            "value": {"stringValue": "ptp"},
                        }
                    ]
                },
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "robotics.message.age",
                                "unit": "ms",
                                "gauge": {
                                    "dataPoints": [
                                        {
                                            "timeUnixNano": "1000000000",
                                            "asDouble": 12.5,
                                            "attributes": [
                                                {
                                                    "key": "robotics.clock.source",
                                                    "value": {"stringValue": "pmc"},
                                                }
                                            ],
                                        }
                                    ]
                                },
                            },
                            {
                                "name": "robotics.message.lost",
                                "unit": "1",
                                "sum": {
                                    "aggregationTemporality": 2,
                                    "isMonotonic": True,
                                    "dataPoints": [
                                        {
                                            "timeUnixNano": "1000000000",
                                            "asInt": "0",
                                        }
                                    ],
                                },
                            },
                        ]
                    }
                ],
            }
        ]
    }
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    samples = load_otlp_json_metrics(path)

    assert [(sample.name, sample.value, sample.unit) for sample in samples] == [
        ("robotics.message.age", 12.5, "ms"),
        ("robotics.message.lost", 0.0, "1"),
    ]
    assert samples[0].attributes == {
        "robotics.clock.sync_protocol": "ptp",
        "robotics.clock.source": "pmc",
    }
    assert samples[1].attributes == {"robotics.clock.sync_protocol": "ptp"}


def test_invalid_otlp_json_reports_line(tmp_path: Path) -> None:
    path = tmp_path / "metrics.json"
    path.write_text("{}\nnot-json\n", encoding="utf-8")

    with pytest.raises(MetricInputError, match=":2"):
        load_otlp_json_metrics(path)

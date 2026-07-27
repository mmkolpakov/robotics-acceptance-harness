from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from os import name as os_name
from pathlib import Path

import pytest
import yaml
from junitparser import JUnitXml
from robotics_runtime_contracts import migrate_scenario_v1_to_v2

from robotics_acceptance_harness.application import VerificationError, run_verification
from robotics_acceptance_harness.documents import load_bundle
from robotics_acceptance_harness.metrics import MetricSample
from robotics_acceptance_harness.readiness import GraphSnapshot, TopicObservation
from robotics_acceptance_harness.timing import ClockSample

FIXTURES = Path(__file__).parent / "fixtures" / "simulation"
PHYSICAL_FIXTURES = Path(__file__).parent / "fixtures" / "physical"
SIMULATION_RUN_ID = "run-6ba7b810-9dad-41d1-80b4-00c04fd430c8"
PHYSICAL_RUN_ID = "run-6ba7b811-9dad-41d1-80b4-00c04fd430c8"


class FakeTime:
    def __init__(self) -> None:
        self.value_ns = 0

    def now_ns(self) -> int:
        return self.value_ns

    def sleep(self, seconds: float) -> None:
        self.value_ns += int(seconds * 1_000_000_000)


class FakeObserver:
    def __init__(self, clock: FakeTime, *, source_scale: float = 1.0) -> None:
        self.clock = clock
        self.source_scale = source_scale
        self._clock_samples: list[ClockSample] = []
        self.closed = False

    @property
    def clock_samples(self) -> tuple[ClockSample, ...]:
        return tuple(self._clock_samples)

    def snapshot(self) -> GraphSnapshot:
        if not self._clock_samples or self._clock_samples[-1].observed_at_ns != self.clock.value_ns:
            self._clock_samples.append(
                ClockSample(
                    self.clock.value_ns,
                    int(self.clock.value_ns * self.source_scale),
                )
            )
        return GraphSnapshot(
            observed_at_ns=self.clock.value_ns,
            topics={
                "/clock": TopicObservation(
                    types=("rosgraph_msgs/msg/Clock",),
                    publishers=1,
                    subscribers=0,
                    first_message_at_ns=0,
                )
            },
        )

    def close(self) -> None:
        self.closed = True


class FakePhysicalObserver:
    def __init__(self, clock: FakeTime, *, forbidden_publishers: int = 0) -> None:
        self.clock = clock
        self.forbidden_publishers = forbidden_publishers
        self.closed = False

    @property
    def clock_samples(self) -> tuple[ClockSample, ...]:
        return ()

    def snapshot(self) -> GraphSnapshot:
        return GraphSnapshot(
            observed_at_ns=self.clock.value_ns,
            topics={
                "/cmd_vel": TopicObservation(
                    types=("geometry_msgs/msg/Twist",),
                    publishers=self.forbidden_publishers,
                    subscribers=0,
                )
            },
        )

    def close(self) -> None:
        self.closed = True


def _write_hardware_metrics(path: Path, *, offset_ms: float) -> None:
    observed_at_ns = int(datetime(2026, 7, 12, 10, 0, 30, tzinfo=UTC).timestamp() * 1_000_000_000)
    attributes = [
        {
            "key": "robotics.clock.sync_protocol",
            "value": {"stringValue": "mavlink_timesync"},
        },
        {
            "key": "robotics.clock.source",
            "value": {"stringValue": "mavlink_timesync_status"},
        },
    ]
    metrics = []
    for name, unit, values in (
        ("robotics.hardware.clock.offset", "ms", (offset_ms, offset_ms + 0.1)),
        ("robotics.hardware.clock.drift", "ppm", (2.0, 2.0)),
        ("robotics.hardware.message.age", "ms", (5.0, 5.0)),
        ("robotics.hardware.clock.monotonic", "1", (1.0, 1.0)),
    ):
        metrics.append(
            {
                "name": name,
                "unit": unit,
                "gauge": {
                    "dataPoints": [
                        {"timeUnixNano": str(timestamp), "asDouble": value}
                        for timestamp, value in zip(
                            (observed_at_ns, observed_at_ns + 1_000_000_000),
                            values,
                            strict=True,
                        )
                    ]
                },
            }
        )
    payload = {
        "resourceMetrics": [
            {
                "resource": {"attributes": attributes},
                "scopeMetrics": [{"metrics": metrics}],
            }
        ]
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_evidence_index(path: Path, metrics_path: Path, *, run_id: str) -> None:
    local_path = metrics_path.as_posix()
    if os_name == "nt":
        local_path = f"/{local_path}"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "evidence-index.v1",
                "run_id": run_id,
                "generated_at": "2026-07-12T10:01:00Z",
                "finalized": True,
                "segments": [
                    {
                        "uri": metrics_path.as_uri(),
                        "local_path": local_path,
                        "media_type": "application/json",
                        "sha256": sha256(metrics_path.read_bytes()).hexdigest(),
                        "size_bytes": metrics_path.stat().st_size,
                        "retention_class": "hil-30d",
                        "segment_index": 0,
                        "upload_status": "local",
                        "checksum_verified": True,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _run_scoped_bundle(
    tmp_path: Path,
    *,
    schema_version: str = "acceptance-scenario.v2",
):
    scenario = yaml.safe_load((FIXTURES / "scenario.yaml").read_text(encoding="utf-8"))
    scenario["timeouts"]["stable_for_sec"] = 0
    scenario["timeouts"]["execution_sec"] = 0.2
    migrated = migrate_scenario_v1_to_v2(
        scenario,
        metric_attributes={},
        time_authority_min_samples=30,
        max_clock_offset_p50_ms=1,
        max_clock_offset_p95_ms=2,
        max_clock_offset_ms=5,
    )
    migrated["schema_version"] = schema_version
    scenario_path = tmp_path / f"{schema_version}.yaml"
    scenario_path.write_text(
        yaml.safe_dump(migrated, sort_keys=False),
        encoding="utf-8",
    )
    return load_bundle(scenario_path, runtime_path=FIXTURES / "runtime.yaml")


def _write_v2_metrics(
    path: Path,
    *,
    timestamps: list[int],
    run_id: str = SIMULATION_RUN_ID,
    domain_id: str = "camera-domain",
) -> None:
    common_attributes = [
        {
            "key": "run.id",
            "value": {"stringValue": run_id},
        },
        {
            "key": "domain.id",
            "value": {"stringValue": domain_id},
        },
        {
            "key": "time.source.id",
            "value": {"stringValue": "simulation-clock"},
        },
    ]
    metrics = [
        {
            "name": "robotics.time_authority.offset",
            "unit": "ms",
            "gauge": {
                "dataPoints": [
                    {"timeUnixNano": str(timestamp), "asDouble": 0.1} for timestamp in timestamps
                ]
            },
        },
        {
            "name": "robotics.message.age",
            "unit": "ms",
            "gauge": {
                "dataPoints": [
                    {"timeUnixNano": "1500000000", "asDouble": 1.0},
                ]
            },
        },
        {
            "name": "robotics.message.loss_ratio",
            "unit": "1",
            "gauge": {
                "dataPoints": [
                    {"timeUnixNano": "1500000000", "asDouble": 0.0},
                ]
            },
        },
        {
            "name": "robotics.simulation.deadline_miss_ratio",
            "unit": "1",
            "gauge": {
                "dataPoints": [
                    {"timeUnixNano": "1500000000", "asDouble": 0.0},
                ]
            },
        },
    ]
    payload = {
        "resourceMetrics": [
            {
                "resource": {"attributes": common_attributes},
                "scopeMetrics": [{"metrics": metrics}],
            }
        ]
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_v2_evidence_index(path: Path, metrics_path: Path) -> None:
    local_path = metrics_path.resolve().as_posix()
    if os_name == "nt":
        local_path = f"/{local_path}"
    payload = metrics_path.read_bytes()
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "evidence-index.v2",
                "run_id": SIMULATION_RUN_ID,
                "generated_at": "2026-07-26T12:00:02Z",
                "finalized": True,
                "policy_observation": {
                    "recording_mode": "on_failure",
                    "compression": "zstd",
                    "upload_mode": "local_only",
                    "remote_sink_used": False,
                    "spool_peak_size_bytes": len(payload),
                    "upload_lag_max_sec": 0,
                },
                "segments": [
                    {
                        "uri": metrics_path.resolve().as_uri(),
                        "local_path": local_path,
                        "media_type": "application/json",
                        "sha256": sha256(payload).hexdigest(),
                        "size_bytes": len(payload),
                        "retention_class": "pull-request-7d",
                        "segment_index": 0,
                        "upload_status": "local",
                        "checksum_verified": True,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_run_context(path: Path, bundle) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "acceptance-run.v1",
                "run_id": SIMULATION_RUN_ID,
                "created_at": "2026-07-26T12:00:00Z",
                "scenario_id": bundle.scenario.data["scenario_id"],
                "scenario_sha256": bundle.scenario.sha256,
                "time_authority": {
                    "kind": "sim_clock",
                    "source_id": "simulation-clock",
                },
                "domains": [
                    {"domain_id": "camera-domain", "role": "sensor"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _run_physical(
    tmp_path: Path,
    *,
    forbidden_publishers: int = 0,
    offset_ms: float = 0.5,
) -> tuple[dict[str, object], Path, FakePhysicalObserver]:
    bundle = load_bundle(
        PHYSICAL_FIXTURES / "hil-scenario.yaml",
        runtime_path=PHYSICAL_FIXTURES / "hil-runtime.json",
        permit_path=PHYSICAL_FIXTURES / "hil-permit.json",
        verification_path=PHYSICAL_FIXTURES / "hil-verification.json",
        now=datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
    )
    metrics_path = tmp_path / "hardware-timing.otlp.json"
    _write_hardware_metrics(metrics_path, offset_ms=offset_ms)
    evidence_path = tmp_path / "evidence-index.yaml"
    _write_evidence_index(evidence_path, metrics_path, run_id=PHYSICAL_RUN_ID)
    clock = FakeTime()
    observer = FakePhysicalObserver(clock, forbidden_publishers=forbidden_publishers)
    started = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
    timestamps = iter((started, started + timedelta(seconds=123)))
    measurement_start_ns = int(started.timestamp() * 1_000_000_000)
    measurement_timestamps = iter(
        (
            measurement_start_ns,
            measurement_start_ns + 123 * 1_000_000_000,
        )
    )
    outputs = run_verification(
        run_id=PHYSICAL_RUN_ID,
        bundle=bundle,
        evidence_index_path=evidence_path,
        otel_metrics_path=metrics_path,
        output_dir=tmp_path / "output",
        observer_factory=lambda *_args, **_kwargs: observer,
        now_ns=clock.now_ns,
        wall_time_ns=lambda: next(measurement_timestamps),
        sleep_fn=clock.sleep,
        utc_now=lambda: next(timestamps),
        poll_interval_sec=0.05,
    )
    return dict(outputs.result), outputs.junit_path, observer


def test_verification_observes_without_starting_runtime(tmp_path: Path) -> None:
    scenario = yaml.safe_load((FIXTURES / "scenario.yaml").read_text(encoding="utf-8"))
    scenario["timeouts"]["stable_for_sec"] = 0
    scenario["timeouts"]["execution_sec"] = 0.2
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")
    bundle = load_bundle(scenario_path, runtime_path=FIXTURES / "runtime.yaml")

    evidence_path = tmp_path / "evidence-index.yaml"
    evidence_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "evidence-index.v1",
                "run_id": SIMULATION_RUN_ID,
                "generated_at": "2026-07-11T12:01:00Z",
                "finalized": True,
                "segments": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    clock = FakeTime()
    observer = FakeObserver(clock)
    started = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    timestamps = iter((started, started + timedelta(seconds=1)))
    measurement_timestamps = iter((0, 2))

    outputs = run_verification(
        run_id=SIMULATION_RUN_ID,
        bundle=bundle,
        evidence_index_path=evidence_path,
        metric_samples=(MetricSample("robotics.simulation.deadline_miss_ratio", 0.0, "1", 1),),
        output_dir=tmp_path / "output",
        observer_factory=lambda *_args, **_kwargs: observer,
        now_ns=clock.now_ns,
        wall_time_ns=lambda: next(measurement_timestamps),
        sleep_fn=clock.sleep,
        utc_now=lambda: next(timestamps),
        poll_interval_sec=0.05,
    )

    assert outputs.result["status"] == "passed"
    assert outputs.result_path.is_file()
    assert outputs.junit_path.is_file()
    assert observer.closed


@pytest.mark.parametrize(
    "schema_version",
    ["acceptance-scenario.v2", "acceptance-scenario.v3"],
)
def test_run_scoped_verification_requires_domain_and_run_context(
    tmp_path: Path,
    schema_version: str,
) -> None:
    with pytest.raises(
        VerificationError,
        match="run-scoped verification requires domain_id and run_context_path",
    ):
        run_verification(
            run_id=SIMULATION_RUN_ID,
            bundle=_run_scoped_bundle(tmp_path, schema_version=schema_version),
            evidence_index_path=tmp_path / "evidence-index.yaml",
            otel_metrics_path=tmp_path / "metrics.otlp.json",
            output_dir=tmp_path / "output",
        )


def test_time_authority_rejects_samples_outside_measurement_window(tmp_path: Path) -> None:
    bundle = _run_scoped_bundle(tmp_path)
    metrics_path = tmp_path / "metrics.otlp.json"
    _write_v2_metrics(metrics_path, timestamps=list(range(100, 130)))
    evidence_path = tmp_path / "evidence-index-v2.yaml"
    _write_v2_evidence_index(evidence_path, metrics_path)
    run_context_path = tmp_path / "acceptance-run.yaml"
    _write_run_context(run_context_path, bundle)
    clock = FakeTime()
    observer = FakeObserver(clock)
    started = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    lifecycle_timestamps = iter((started, started + timedelta(seconds=1)))
    measurement_timestamps = iter((1_000_000_000, 2_000_000_000))

    outputs = run_verification(
        run_id=SIMULATION_RUN_ID,
        domain_id="camera-domain",
        run_context_path=run_context_path,
        bundle=bundle,
        evidence_index_path=evidence_path,
        otel_metrics_path=metrics_path,
        output_dir=tmp_path / "output",
        observer_factory=lambda *_args, **_kwargs: observer,
        now_ns=clock.now_ns,
        wall_time_ns=lambda: next(measurement_timestamps),
        sleep_fn=clock.sleep,
        utc_now=lambda: next(lifecycle_timestamps),
        poll_interval_sec=0.05,
    )

    observation = outputs.result["time_authority_observation"]
    assert observation["window_start_ns"] == 1_000_000_000
    assert observation["window_end_ns"] == 2_000_000_000
    assert observation["sample_count"] == 0
    assert observation["within_policy"] is False
    assert outputs.result["status"] != "passed"


def test_v2_verification_ignores_metrics_from_another_run(tmp_path: Path) -> None:
    bundle = _run_scoped_bundle(tmp_path)
    metrics_path = tmp_path / "metrics.otlp.json"
    _write_v2_metrics(
        metrics_path,
        timestamps=list(range(1_000_000_000, 1_000_000_030)),
        run_id="run-00000000-0000-4000-8000-000000000001",
    )
    evidence_path = tmp_path / "evidence-index-v2.yaml"
    _write_v2_evidence_index(evidence_path, metrics_path)
    run_context_path = tmp_path / "acceptance-run.yaml"
    _write_run_context(run_context_path, bundle)
    clock = FakeTime()
    observer = FakeObserver(clock)
    started = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    lifecycle_timestamps = iter((started, started + timedelta(seconds=1)))
    measurement_timestamps = iter((1_000_000_000, 2_000_000_000))

    outputs = run_verification(
        run_id=SIMULATION_RUN_ID,
        domain_id="camera-domain",
        run_context_path=run_context_path,
        bundle=bundle,
        evidence_index_path=evidence_path,
        otel_metrics_path=metrics_path,
        output_dir=tmp_path / "output",
        observer_factory=lambda *_args, **_kwargs: observer,
        now_ns=clock.now_ns,
        wall_time_ns=lambda: next(measurement_timestamps),
        sleep_fn=clock.sleep,
        utc_now=lambda: next(lifecycle_timestamps),
        poll_interval_sec=0.05,
    )

    assert outputs.result["time_authority_observation"]["sample_count"] == 0
    assert outputs.result["status"] == "error"


def test_timing_policy_failure_emits_result_and_junit(tmp_path: Path) -> None:
    scenario = yaml.safe_load((FIXTURES / "scenario.yaml").read_text(encoding="utf-8"))
    scenario["timeouts"]["stable_for_sec"] = 0
    scenario["timeouts"]["execution_sec"] = 0.2
    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")
    bundle = load_bundle(scenario_path, runtime_path=FIXTURES / "runtime.yaml")
    evidence_path = tmp_path / "evidence-index.yaml"
    evidence_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "evidence-index.v1",
                "run_id": SIMULATION_RUN_ID,
                "generated_at": "2026-07-11T12:01:00Z",
                "finalized": True,
                "segments": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    clock = FakeTime()
    observer = FakeObserver(clock, source_scale=0.5)
    started = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    timestamps = iter((started, started + timedelta(seconds=1)))
    measurement_timestamps = iter((0, 2))

    outputs = run_verification(
        run_id=SIMULATION_RUN_ID,
        bundle=bundle,
        evidence_index_path=evidence_path,
        metric_samples=(MetricSample("robotics.simulation.deadline_miss_ratio", 0.0, "1", 1),),
        output_dir=tmp_path / "output",
        observer_factory=lambda *_args, **_kwargs: observer,
        now_ns=clock.now_ns,
        wall_time_ns=lambda: next(measurement_timestamps),
        sleep_fn=clock.sleep,
        utc_now=lambda: next(timestamps),
        poll_interval_sec=0.05,
    )

    assert outputs.result["status"] == "failed"
    assert outputs.result_path.is_file()
    assert JUnitXml.fromfile(outputs.junit_path).failures == 1


def test_physical_verification_emits_canonical_result_from_verified_evidence(
    tmp_path: Path,
) -> None:
    result, junit_path, observer = _run_physical(tmp_path)

    assert result["schema_version"] == "acceptance-result.v1"
    assert result["status"] == "passed"
    assert result["authorization"]["mode"] == "verified_execution_permit"
    assert result["forbidden_graph_observation"]["passed"] is True
    assert result["hardware_clock_observation"]["within_policy"] is True
    assert (
        result["hardware_clock_observation"]["evidence_sha256"] == result["evidence"][0]["sha256"]
    )
    assert JUnitXml.fromfile(junit_path).failures == 0
    assert observer.closed


def test_physical_verification_requires_file_backed_timing_evidence(tmp_path: Path) -> None:
    bundle = load_bundle(
        PHYSICAL_FIXTURES / "hil-scenario.yaml",
        runtime_path=PHYSICAL_FIXTURES / "hil-runtime.json",
        permit_path=PHYSICAL_FIXTURES / "hil-permit.json",
        verification_path=PHYSICAL_FIXTURES / "hil-verification.json",
        now=datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
    )

    with pytest.raises(VerificationError, match="requires --otel-metrics evidence"):
        run_verification(
            run_id=PHYSICAL_RUN_ID,
            bundle=bundle,
            evidence_index_path=tmp_path / "evidence-index.yaml",
            output_dir=tmp_path / "output",
        )


def test_physical_verification_fails_on_transient_command_publisher(tmp_path: Path) -> None:
    result, junit_path, _observer = _run_physical(tmp_path, forbidden_publishers=1)

    assert result["status"] == "failed"
    assert result["forbidden_graph_observation"]["violations"] == [
        {"kind": "topic", "name": "/cmd_vel"}
    ]
    assert JUnitXml.fromfile(junit_path).failures == 1


def test_physical_verification_fails_when_hardware_clock_exceeds_policy(
    tmp_path: Path,
) -> None:
    result, junit_path, _observer = _run_physical(tmp_path, offset_ms=10)

    assert result["status"] == "failed"
    assert result["hardware_clock_observation"]["within_policy"] is False
    assert JUnitXml.fromfile(junit_path).failures == 1

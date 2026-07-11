from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from robotics_acceptance_harness.application import run_verification
from robotics_acceptance_harness.documents import load_bundle
from robotics_acceptance_harness.metrics import MetricSample
from robotics_acceptance_harness.readiness import GraphSnapshot, TopicObservation
from robotics_acceptance_harness.timing import ClockSample

FIXTURES = Path(__file__).parent / "fixtures" / "v2"


class FakeTime:
    def __init__(self) -> None:
        self.value_ns = 0

    def now_ns(self) -> int:
        return self.value_ns

    def sleep(self, seconds: float) -> None:
        self.value_ns += int(seconds * 1_000_000_000)


class FakeObserver:
    def __init__(self, clock: FakeTime) -> None:
        self.clock = clock
        self._clock_samples: list[ClockSample] = []
        self.closed = False

    @property
    def clock_samples(self) -> tuple[ClockSample, ...]:
        return tuple(self._clock_samples)

    def snapshot(self) -> GraphSnapshot:
        if not self._clock_samples or self._clock_samples[-1].observed_at_ns != self.clock.value_ns:
            self._clock_samples.append(ClockSample(self.clock.value_ns, self.clock.value_ns))
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


def test_verification_observes_without_starting_runtime(tmp_path: Path) -> None:
    scenario = yaml.safe_load((FIXTURES / "simulation.yaml").read_text(encoding="utf-8"))
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
                "run_id": "org.example.physics-smoke",
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

    outputs = run_verification(
        bundle=bundle,
        evidence_index_path=evidence_path,
        metric_samples=(MetricSample("robotics.simulation.deadline_miss_ratio", 0.0, "1", 1),),
        output_dir=tmp_path / "output",
        observer_factory=lambda *_args, **_kwargs: observer,
        now_ns=clock.now_ns,
        sleep_fn=clock.sleep,
        utc_now=lambda: next(timestamps),
        poll_interval_sec=0.05,
    )

    assert outputs.result["status"] == "passed"
    assert outputs.result_path.is_file()
    assert outputs.junit_path.is_file()
    assert observer.closed

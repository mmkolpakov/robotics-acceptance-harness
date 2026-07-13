from __future__ import annotations

from robotics_acceptance_harness.forbidden_graph import ForbiddenGraphMonitor
from robotics_acceptance_harness.readiness import (
    EndpointObservation,
    GraphSnapshot,
    TopicObservation,
)

FORBIDDEN = {
    "topics": ["/cmd_vel"],
    "services": ["/arm"],
    "actions": ["/takeoff"],
}


def snapshot(*, publisher: int = 0, service: int = 0, action: int = 0) -> GraphSnapshot:
    return GraphSnapshot(
        observed_at_ns=1,
        topics={"/cmd_vel": TopicObservation((), publisher, 0)},
        services={"/arm": EndpointObservation((), service)},
        actions={"/takeoff": EndpointObservation((), action)},
    )


def test_forbidden_graph_monitor_passes_when_interfaces_are_absent() -> None:
    monitor = ForbiddenGraphMonitor(FORBIDDEN)
    monitor.observe(snapshot())

    observation = monitor.result()

    assert observation.passed
    assert observation.checked_topics == ("/cmd_vel",)
    assert observation.checked_services == ("/arm",)
    assert observation.checked_actions == ("/takeoff",)


def test_forbidden_graph_monitor_retains_transient_violations() -> None:
    monitor = ForbiddenGraphMonitor(FORBIDDEN)
    monitor.observe(snapshot(publisher=1, service=1))
    monitor.observe(snapshot())

    observation = monitor.result()

    assert not observation.passed
    assert [(item.kind, item.name) for item in observation.violations] == [
        ("service", "/arm"),
        ("topic", "/cmd_vel"),
    ]

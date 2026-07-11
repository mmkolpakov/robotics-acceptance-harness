from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from time import monotonic_ns, sleep
from types import MappingProxyType
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class TopicObservation:
    types: tuple[str, ...]
    publishers: int
    subscribers: int
    first_message_at_ns: int | None = None
    qos_compatible: bool = True


@dataclass(frozen=True, slots=True)
class EndpointObservation:
    types: tuple[str, ...]
    servers: int


@dataclass(frozen=True, slots=True)
class LifecycleObservation:
    state: str
    observed_at_ns: int


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    observed_at_ns: int
    topics: Mapping[str, TopicObservation] = field(default_factory=dict)
    services: Mapping[str, EndpointObservation] = field(default_factory=dict)
    actions: Mapping[str, EndpointObservation] = field(default_factory=dict)
    lifecycle_nodes: Mapping[str, LifecycleObservation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "topics", MappingProxyType(dict(self.topics)))
        object.__setattr__(self, "services", MappingProxyType(dict(self.services)))
        object.__setattr__(self, "actions", MappingProxyType(dict(self.actions)))
        object.__setattr__(self, "lifecycle_nodes", MappingProxyType(dict(self.lifecycle_nodes)))


class GraphObserver(Protocol):
    """Read-only source of ROS graph snapshots."""

    def snapshot(self) -> GraphSnapshot: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ReadinessIssue:
    json_path: str
    message: str


class GraphReadinessTimeout(TimeoutError):
    """Raised when the expected graph never remains ready for the required window."""

    def __init__(self, issues: tuple[ReadinessIssue, ...]) -> None:
        self.issues = issues
        detail = "; ".join(f"{issue.json_path}: {issue.message}" for issue in issues)
        super().__init__(detail or "ROS graph did not remain stable before timeout")


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    snapshot: GraphSnapshot
    first_ready_at_ns: int
    stable_for_sec: float


def _check_topics(
    expected_topics: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    snapshot: GraphSnapshot,
) -> list[ReadinessIssue]:
    issues: list[ReadinessIssue] = []
    for index, expected in enumerate(expected_topics):
        path = f"$.expected_ros_graph.topics[{index}]"
        name = expected["name"]
        observed = snapshot.topics.get(name)
        if observed is None:
            issues.append(ReadinessIssue(path, f"topic {name} is absent"))
            continue
        if expected["type"] not in observed.types:
            issues.append(
                ReadinessIssue(
                    f"{path}.type",
                    f"expected {expected['type']}; observed {observed.types}",
                )
            )
        if observed.publishers < expected["min_publishers"]:
            issues.append(
                ReadinessIssue(
                    f"{path}.min_publishers",
                    f"expected at least {expected['min_publishers']}; "
                    f"observed {observed.publishers}",
                )
            )
        if observed.subscribers < expected["min_subscribers"]:
            issues.append(
                ReadinessIssue(
                    f"{path}.min_subscribers",
                    f"expected at least {expected['min_subscribers']}; "
                    f"observed {observed.subscribers}",
                )
            )
        if not observed.qos_compatible:
            issues.append(
                ReadinessIssue(
                    f"{path}.qos_profile",
                    "publisher and subscriber QoS policies are incompatible",
                )
            )
        if observed.first_message_at_ns is None:
            issues.append(
                ReadinessIssue(
                    f"{path}.first_message_timeout_sec",
                    "no message has been observed",
                )
            )
    return issues


def _check_endpoints(
    kind: str,
    expected_endpoints: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    observed_endpoints: Mapping[str, EndpointObservation],
) -> list[ReadinessIssue]:
    issues: list[ReadinessIssue] = []
    for index, expected in enumerate(expected_endpoints):
        path = f"$.expected_ros_graph.{kind}[{index}]"
        name = expected["name"]
        observed = observed_endpoints.get(name)
        if observed is None or observed.servers < 1:
            issues.append(ReadinessIssue(path, f"{kind[:-1]} server {name} is absent"))
            continue
        if expected["type"] not in observed.types:
            issues.append(
                ReadinessIssue(
                    f"{path}.type",
                    f"expected {expected['type']}; observed {observed.types}",
                )
            )
    return issues


def evaluate_graph(
    expected_graph: Mapping[str, Any],
    snapshot: GraphSnapshot,
) -> tuple[ReadinessIssue, ...]:
    """Evaluate names, types, and endpoint counts in one graph snapshot."""

    issues = _check_topics(expected_graph["topics"], snapshot)
    issues.extend(_check_endpoints("services", expected_graph["services"], snapshot.services))
    issues.extend(_check_endpoints("actions", expected_graph["actions"], snapshot.actions))
    for index, expected in enumerate(expected_graph["lifecycle_nodes"]):
        path = f"$.expected_ros_graph.lifecycle_nodes[{index}]"
        name = expected["name"]
        observed = snapshot.lifecycle_nodes.get(name)
        if observed is None:
            issues.append(ReadinessIssue(path, f"managed node {name} state is unavailable"))
        elif observed.state != expected["required_state"]:
            issues.append(
                ReadinessIssue(
                    f"{path}.required_state",
                    f"expected {expected['required_state']}; observed {observed.state}",
                )
            )
    return tuple(issues)


def wait_for_readiness(
    expected_graph: Mapping[str, Any],
    observer: GraphObserver,
    *,
    timeout_sec: float,
    stable_for_sec: float,
    poll_interval_sec: float = 0.1,
    now_ns: Callable[[], int] = monotonic_ns,
    sleep_fn: Callable[[float], None] = sleep,
) -> ReadinessResult:
    """Wait until every endpoint remains ready for one uninterrupted window."""

    lifecycle_stability = max(
        (float(node["stable_for_sec"]) for node in expected_graph["lifecycle_nodes"]),
        default=0.0,
    )
    required_stability = max(stable_for_sec, lifecycle_stability)
    started_at_ns = now_ns()
    deadline_ns = started_at_ns + int(timeout_sec * 1_000_000_000)
    first_ready_at_ns: int | None = None
    last_issues: tuple[ReadinessIssue, ...] = ()

    while True:
        snapshot = observer.snapshot()
        current_ns = now_ns()
        last_issues = evaluate_graph(expected_graph, snapshot)
        if last_issues:
            first_ready_at_ns = None
        else:
            if first_ready_at_ns is None:
                first_ready_at_ns = current_ns
            stable_ns = current_ns - first_ready_at_ns
            if stable_ns >= int(required_stability * 1_000_000_000):
                return ReadinessResult(
                    snapshot=snapshot,
                    first_ready_at_ns=first_ready_at_ns,
                    stable_for_sec=stable_ns / 1_000_000_000,
                )
        if current_ns >= deadline_ns:
            raise GraphReadinessTimeout(last_issues)
        sleep_fn(poll_interval_sec)


__all__ = [
    "EndpointObservation",
    "GraphReadinessTimeout",
    "GraphObserver",
    "GraphSnapshot",
    "LifecycleObservation",
    "ReadinessIssue",
    "ReadinessResult",
    "TopicObservation",
    "evaluate_graph",
    "wait_for_readiness",
]

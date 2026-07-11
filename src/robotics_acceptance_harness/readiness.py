from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
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
class GraphSnapshot:
    observed_at_ns: int
    topics: Mapping[str, TopicObservation] = field(default_factory=dict)
    services: Mapping[str, EndpointObservation] = field(default_factory=dict)
    actions: Mapping[str, EndpointObservation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "topics", MappingProxyType(dict(self.topics)))
        object.__setattr__(self, "services", MappingProxyType(dict(self.services)))
        object.__setattr__(self, "actions", MappingProxyType(dict(self.actions)))


class GraphObserver(Protocol):
    """Read-only source of ROS graph snapshots."""

    def snapshot(self) -> GraphSnapshot: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ReadinessIssue:
    json_path: str
    message: str


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
    return tuple(issues)


__all__ = [
    "EndpointObservation",
    "GraphObserver",
    "GraphSnapshot",
    "ReadinessIssue",
    "TopicObservation",
    "evaluate_graph",
]

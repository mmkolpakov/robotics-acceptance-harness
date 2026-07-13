from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from robotics_acceptance_harness.readiness import GraphSnapshot


@dataclass(frozen=True, order=True, slots=True)
class ForbiddenGraphViolation:
    kind: Literal["topic", "service", "action"]
    name: str


@dataclass(frozen=True, slots=True)
class ForbiddenGraphObservation:
    checked_topics: tuple[str, ...]
    checked_services: tuple[str, ...]
    checked_actions: tuple[str, ...]
    violations: tuple[ForbiddenGraphViolation, ...]

    @property
    def passed(self) -> bool:
        return not self.violations


def find_forbidden_graph_violations(
    forbidden_graph: Mapping[str, Any],
    snapshot: GraphSnapshot,
) -> tuple[ForbiddenGraphViolation, ...]:
    """Find command publishers and command servers in one read-only snapshot."""

    violations: list[ForbiddenGraphViolation] = []
    for name in forbidden_graph["topics"]:
        observed = snapshot.topics.get(str(name))
        if observed is not None and observed.publishers > 0:
            violations.append(ForbiddenGraphViolation("topic", str(name)))
    for name in forbidden_graph["services"]:
        observed_service = snapshot.services.get(str(name))
        if observed_service is not None and observed_service.servers > 0:
            violations.append(ForbiddenGraphViolation("service", str(name)))
    for name in forbidden_graph["actions"]:
        observed_action = snapshot.actions.get(str(name))
        if observed_action is not None and observed_action.servers > 0:
            violations.append(ForbiddenGraphViolation("action", str(name)))
    return tuple(sorted(violations))


class ForbiddenGraphMonitor:
    """Accumulate transient forbidden ROS interfaces across an observation window."""

    def __init__(self, forbidden_graph: Mapping[str, Any]) -> None:
        self._forbidden_graph = forbidden_graph
        self._violations: set[ForbiddenGraphViolation] = set()

    def observe(self, snapshot: GraphSnapshot) -> None:
        self._violations.update(find_forbidden_graph_violations(self._forbidden_graph, snapshot))

    def result(self) -> ForbiddenGraphObservation:
        return ForbiddenGraphObservation(
            checked_topics=tuple(sorted(str(name) for name in self._forbidden_graph["topics"])),
            checked_services=tuple(sorted(str(name) for name in self._forbidden_graph["services"])),
            checked_actions=tuple(sorted(str(name) for name in self._forbidden_graph["actions"])),
            violations=tuple(sorted(self._violations)),
        )


__all__ = [
    "ForbiddenGraphMonitor",
    "ForbiddenGraphObservation",
    "ForbiddenGraphViolation",
    "find_forbidden_graph_violations",
]

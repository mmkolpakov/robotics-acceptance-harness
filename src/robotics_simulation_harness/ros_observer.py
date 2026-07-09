from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class GraphObservationResult:
    ok: bool
    message: str
    observed: dict[str, Any]


class RosObserverError(RuntimeError):
    pass


def _action_service_names(action_name: str) -> tuple[str, str]:
    return f"{action_name}/_action/send_goal", f"{action_name}/_action/get_result"


def _action_status_topic(action_name: str) -> str:
    return f"{action_name}/_action/status"


def observe_ros_graph(graph: dict[str, Any], *, wall_timeout_sec: int) -> GraphObservationResult:
    try:
        import rclpy
        from rclpy.node import Node
    except ImportError as exc:  # pragma: no cover - depends on host ROS install
        raise RosObserverError("rclpy is required for ROS graph observation") from exc

    rclpy.init()
    node = Node("robotics_harness_observer")
    observed: dict[str, Any] = {"topics": {}, "services": {}, "actions": {}}
    deadline = time.monotonic() + wall_timeout_sec
    try:
        for topic in graph.get("topics", []):
            name = topic["name"]
            pub_needed = int(topic["publisher_match"]["min_count"])
            sub_needed = int(topic["subscriber_match"]["min_count"])
            topic_deadline = min(
                deadline,
                time.monotonic() + int(topic["publisher_match"]["timeout_sec"]),
            )
            while True:
                pubs = node.count_publishers(name)
                subs = node.count_subscribers(name)
                observed["topics"][name] = {"publishers": pubs, "subscribers": subs}
                if pubs >= pub_needed and subs >= sub_needed:
                    break
                if time.monotonic() >= topic_deadline:
                    return GraphObservationResult(
                        ok=False,
                        message=f"topic readiness failed for {name}",
                        observed=observed,
                    )
                rclpy.spin_once(node, timeout_sec=0.2)

        for service in graph.get("services", []):
            name = service["name"]
            service_deadline = min(
                deadline,
                time.monotonic() + int(service["ready_timeout_sec"]),
            )
            while True:
                known = dict(node.get_service_names_and_types())
                available = name in known
                observed["services"][name] = {"available": available}
                if available:
                    break
                if time.monotonic() >= service_deadline:
                    return GraphObservationResult(
                        ok=False,
                        message=f"service readiness failed for {name}",
                        observed=observed,
                    )
                rclpy.spin_once(node, timeout_sec=0.2)

        for action in graph.get("actions", []):
            name = action["name"]
            action_deadline = min(
                deadline,
                time.monotonic() + int(action["ready_timeout_sec"]),
            )
            send_goal, get_result = _action_service_names(name)
            status_topic = _action_status_topic(name)
            while True:
                known_services = dict(node.get_service_names_and_types())
                known_topics = {n for n, _ in node.get_topic_names_and_types()}
                available = (
                    send_goal in known_services
                    and get_result in known_services
                    and status_topic in known_topics
                )
                observed["actions"][name] = {"available": available}
                if available:
                    break
                if time.monotonic() >= action_deadline:
                    return GraphObservationResult(
                        ok=False,
                        message=f"action readiness failed for {name}",
                        observed=observed,
                    )
                rclpy.spin_once(node, timeout_sec=0.2)

        if graph.get("require_clock") and "/clock" not in observed["topics"]:
            return GraphObservationResult(
                ok=False,
                message="/clock required but not observed",
                observed=observed,
            )
        return GraphObservationResult(ok=True, message="graph ready", observed=observed)
    finally:
        node.destroy_node()
        rclpy.shutdown()

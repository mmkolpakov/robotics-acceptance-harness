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


def observe_ros_graph(graph: dict[str, Any], *, wall_timeout_sec: int) -> GraphObservationResult:
    try:
        import rclpy
        from rclpy.node import Node
    except ImportError as exc:  # pragma: no cover - depends on host ROS install
        raise RosObserverError("rclpy is required for ROS graph observation") from exc

    rclpy.init()
    node = Node("robotics_harness_observer")
    observed: dict[str, Any] = {"topics": {}}
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
            while time.monotonic() < topic_deadline:
                pubs = node.count_publishers(name)
                subs = node.count_subscribers(name)
                observed["topics"][name] = {"publishers": pubs, "subscribers": subs}
                if pubs >= pub_needed and subs >= sub_needed:
                    break
                rclpy.spin_once(node, timeout_sec=0.2)
            else:
                return GraphObservationResult(
                    ok=False,
                    message=f"topic readiness failed for {name}",
                    observed=observed,
                )
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

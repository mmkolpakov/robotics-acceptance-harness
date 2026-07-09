from __future__ import annotations

import time
from collections.abc import Callable
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


class SimClock:
    """Tracks `/clock` so readiness deadlines can be measured in simulation
    time instead of wall-clock monotonic time alone.

    Gazebo (and any other sim) can run slower or faster than real time, and a
    purely wall-clock deadline either times out a healthy-but-slow simulation
    or waits far too long on a fast one. `elapsed()` reports how much time
    has passed *since this SimClock was created* in whichever clock is
    actually available: the first `/clock` message observed establishes the
    sim-time origin, and every reading after that is measured against it.
    Graphs that never publish `/clock` simply never establish that origin,
    so `elapsed()` transparently falls back to wall-clock elapsed time and
    behaves exactly as before.
    """

    def __init__(self) -> None:
        self.sim_sec: float | None = None
        self._session_start_sim: float | None = None
        self._session_start_wall = time.monotonic()

    def callback(self, msg: Any) -> None:
        self.sim_sec = msg.clock.sec + msg.clock.nanosec / 1e9
        if self._session_start_sim is None:
            self._session_start_sim = self.sim_sec

    def elapsed(self) -> float:
        if self.sim_sec is not None and self._session_start_sim is not None:
            return self.sim_sec - self._session_start_sim
        return time.monotonic() - self._session_start_wall


@dataclass
class _PendingCheck:
    kind: str
    name: str
    timeout_sec: float
    check: Callable[[], bool]


def observe_ros_graph(graph: dict[str, Any], *, wall_timeout_sec: int) -> GraphObservationResult:
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from rosgraph_msgs.msg import Clock
    except ImportError as exc:  # pragma: no cover - depends on host ROS install
        raise RosObserverError("rclpy is required for ROS graph observation") from exc

    rclpy.init()
    node = Node("robotics_harness_observer")
    sim_clock = SimClock()
    # BEST_EFFORT/KEEP_LAST(1) matches the QoS Gazebo's clock bridge publishes
    # with; a RELIABLE subscription would simply never match and this
    # observer would silently stay on the wall-clock fallback forever.
    clock_qos = QoSProfile(
        depth=1, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST
    )
    node.create_subscription(Clock, "/clock", sim_clock.callback, clock_qos)

    observed: dict[str, Any] = {"topics": {}, "services": {}, "actions": {}}
    hard_deadline = time.monotonic() + wall_timeout_sec
    pending: list[_PendingCheck] = []

    def _add_topic(topic: dict[str, Any]) -> None:
        name = topic["name"]
        pub_needed = int(topic["publisher_match"]["min_count"])
        sub_needed = int(topic["subscriber_match"]["min_count"])
        timeout_sec = int(topic["publisher_match"]["timeout_sec"])

        def check() -> bool:
            pubs = node.count_publishers(name)
            subs = node.count_subscribers(name)
            observed["topics"][name] = {"publishers": pubs, "subscribers": subs}
            return pubs >= pub_needed and subs >= sub_needed

        pending.append(_PendingCheck(kind="topic", name=name, timeout_sec=timeout_sec, check=check))

    def _add_service(service: dict[str, Any]) -> None:
        name = service["name"]
        timeout_sec = int(service["ready_timeout_sec"])

        def check() -> bool:
            available = name in dict(node.get_service_names_and_types())
            observed["services"][name] = {"available": available}
            return available

        pending.append(
            _PendingCheck(kind="service", name=name, timeout_sec=timeout_sec, check=check)
        )

    def _add_action(action: dict[str, Any]) -> None:
        name = action["name"]
        timeout_sec = int(action["ready_timeout_sec"])
        send_goal, get_result = _action_service_names(name)
        status_topic = _action_status_topic(name)

        def check() -> bool:
            known_services = dict(node.get_service_names_and_types())
            known_topics = {n for n, _ in node.get_topic_names_and_types()}
            available = (
                send_goal in known_services
                and get_result in known_services
                and status_topic in known_topics
            )
            observed["actions"][name] = {"available": available}
            return available

        pending.append(
            _PendingCheck(kind="action", name=name, timeout_sec=timeout_sec, check=check)
        )

    for topic in graph.get("topics", []):
        _add_topic(topic)
    for service in graph.get("services", []):
        _add_service(service)
    for action in graph.get("actions", []):
        _add_action(action)

    try:
        # A single spin loop drives readiness for every topic/service/action
        # concurrently: each iteration re-checks *all* still-pending items
        # instead of blocking on one item's full timeout before even
        # starting to look at the next. Sequential per-item loops (the
        # previous implementation) mean an item near the back of the list
        # only starts being observed after every earlier item has already
        # either succeeded or exhausted its own timeout, which both wastes
        # wall time and can misattribute a slow-to-appear later item as
        # "never checked" in the observed report.
        while pending:
            if time.monotonic() >= hard_deadline:
                failed = pending[0]
                return GraphObservationResult(
                    ok=False,
                    message=f"{failed.kind} readiness failed for {failed.name} (wall timeout)",
                    observed=observed,
                )
            rclpy.spin_once(node, timeout_sec=0.2)
            elapsed = sim_clock.elapsed()
            still_pending = []
            for item in pending:
                if item.check():
                    continue
                if elapsed >= item.timeout_sec:
                    return GraphObservationResult(
                        ok=False,
                        message=f"{item.kind} readiness failed for {item.name}",
                        observed=observed,
                    )
                still_pending.append(item)
            pending = still_pending

        if graph.get("require_clock") and "/clock" not in observed["topics"]:
            return GraphObservationResult(
                ok=False, message="/clock required but not observed", observed=observed
            )
        return GraphObservationResult(ok=True, message="graph ready", observed=observed)
    finally:
        node.destroy_node()
        rclpy.shutdown()

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest

from robotics_simulation_harness.ros_observer import SimClock

rclpy = pytest.importorskip("rclpy", reason="rclpy (ROS 2) is required for live graph checks")

from rclpy.node import Node  # noqa: E402
from std_msgs.msg import String  # noqa: E402
from std_srvs.srv import Trigger  # noqa: E402

from robotics_simulation_harness.ros_observer import (  # noqa: E402
    RosObserverError,
    observe_ros_graph,
)


def _clock_msg(sec: int) -> object:
    class _Stamp:
        nanosec = 0

    _Stamp.sec = sec  # type: ignore[attr-defined]

    class _Msg:
        clock = _Stamp()

    return _Msg()


def test_sim_clock_falls_back_to_wall_time_when_no_clock_observed() -> None:
    clock = SimClock()
    time.sleep(0.05)
    assert clock.elapsed() >= 0.04


def test_sim_clock_prefers_sim_time_once_observed() -> None:
    clock = SimClock()
    clock.callback(_clock_msg(100))
    # The first `/clock` message establishes the sim-time origin: elapsed
    # sim time from that exact instant is ~0 regardless of wall time.
    assert clock.elapsed() < 1
    clock.callback(_clock_msg(150))
    # Wall time barely moved, but sim time jumped 50s: the sim-time reading
    # must win so a deadline expressed against sim seconds actually fires.
    assert clock.elapsed() >= 49


@pytest.fixture
def fixture_node() -> Iterator[Node]:
    # `observe_ros_graph` owns the default rclpy context (it calls
    # `rclpy.init()`/`rclpy.shutdown()` itself). The fixture that publishes
    # the "live" graph state under test must use an independent context, or
    # the two `rclpy.init()` calls collide.
    context = rclpy.Context()
    rclpy.init(context=context)
    node = Node("ros_observer_test_fixture", context=context)
    try:
        yield node
    finally:
        node.destroy_node()
        rclpy.shutdown(context=context)


def _topic_graph(name: str, *, pub_min: int, sub_min: int, timeout_sec: int = 2) -> dict:
    return {
        "graph_ready_timeout_sec": timeout_sec,
        "require_clock": False,
        "topics": [
            {
                "name": name,
                "type": "std_msgs/msg/String",
                "publisher_match": {"min_count": pub_min, "timeout_sec": timeout_sec},
                "subscriber_match": {"min_count": sub_min, "timeout_sec": timeout_sec},
            }
        ],
        "services": [],
        "actions": [],
    }


def test_topic_readiness_passes_with_live_publisher(fixture_node: Node) -> None:
    fixture_node.create_publisher(String, "/observer_test/topic_ok", 10)
    result = observe_ros_graph(
        _topic_graph("/observer_test/topic_ok", pub_min=1, sub_min=0),
        wall_timeout_sec=2,
    )
    assert result.ok, result.message
    assert result.observed["topics"]["/observer_test/topic_ok"]["publishers"] >= 1


def test_topic_readiness_fails_without_publisher() -> None:
    result = observe_ros_graph(
        _topic_graph("/observer_test/topic_missing", pub_min=1, sub_min=0, timeout_sec=1),
        wall_timeout_sec=1,
    )
    assert not result.ok
    assert "topic readiness failed" in result.message


def test_service_readiness_passes_with_live_service(fixture_node: Node) -> None:
    fixture_node.create_service(Trigger, "/observer_test/service_ok", lambda req, res: res)
    graph = {
        "graph_ready_timeout_sec": 2,
        "require_clock": False,
        "topics": [],
        "services": [
            {
                "name": "/observer_test/service_ok",
                "type": "std_srvs/srv/Trigger",
                "ready_timeout_sec": 2,
            }
        ],
        "actions": [],
    }
    result = observe_ros_graph(graph, wall_timeout_sec=2)
    assert result.ok, result.message
    assert result.observed["services"]["/observer_test/service_ok"]["available"] is True


def test_service_readiness_fails_without_service() -> None:
    graph = {
        "graph_ready_timeout_sec": 1,
        "require_clock": False,
        "topics": [],
        "services": [
            {
                "name": "/observer_test/service_missing",
                "type": "std_srvs/srv/Trigger",
                "ready_timeout_sec": 1,
            }
        ],
        "actions": [],
    }
    result = observe_ros_graph(graph, wall_timeout_sec=1)
    assert not result.ok
    assert "service readiness failed" in result.message


def test_action_readiness_passes_when_action_interface_is_live(fixture_node: Node) -> None:
    action_name = "/observer_test/move"
    fixture_node.create_service(Trigger, f"{action_name}/_action/send_goal", lambda req, res: res)
    fixture_node.create_service(Trigger, f"{action_name}/_action/get_result", lambda req, res: res)
    fixture_node.create_publisher(String, f"{action_name}/_action/status", 10)
    graph = {
        "graph_ready_timeout_sec": 2,
        "require_clock": False,
        "topics": [],
        "services": [],
        "actions": [
            {
                "name": action_name,
                "type": "example_interfaces/action/Fibonacci",
                "ready_timeout_sec": 2,
            }
        ],
    }
    result = observe_ros_graph(graph, wall_timeout_sec=2)
    assert result.ok, result.message
    assert result.observed["actions"][action_name]["available"] is True


def test_action_readiness_fails_without_action_interface() -> None:
    graph = {
        "graph_ready_timeout_sec": 1,
        "require_clock": False,
        "topics": [],
        "services": [],
        "actions": [
            {
                "name": "/observer_test/missing_action",
                "type": "example_interfaces/action/Fibonacci",
                "ready_timeout_sec": 1,
            }
        ],
    }
    result = observe_ros_graph(graph, wall_timeout_sec=1)
    assert not result.ok
    assert "action readiness failed" in result.message


def test_require_clock_fails_when_clock_topic_absent() -> None:
    graph = {
        "graph_ready_timeout_sec": 1,
        "require_clock": True,
        "topics": [
            {
                "name": "/observer_test/not_clock",
                "type": "std_msgs/msg/String",
                "publisher_match": {"min_count": 0, "timeout_sec": 1},
                "subscriber_match": {"min_count": 0, "timeout_sec": 1},
            }
        ],
        "services": [],
        "actions": [],
    }
    result = observe_ros_graph(graph, wall_timeout_sec=1)
    assert not result.ok
    assert "/clock" in result.message


def test_concurrent_readiness_checks_all_items_in_one_loop(fixture_node: Node) -> None:
    # Topic B's publisher only appears ~0.5s after the observer starts.
    # A sequential-per-item implementation would already have burned most of
    # topic A's own timeout window before even looking at topic B; the
    # concurrent single-loop implementation must pick both up well inside a
    # short shared deadline because it inspects every pending item on each
    # spin iteration.
    fixture_node.create_publisher(String, "/observer_test/concurrent_a", 10)

    def _publish_b_late() -> None:
        time.sleep(0.5)
        fixture_node.create_publisher(String, "/observer_test/concurrent_b", 10)

    threading.Thread(target=_publish_b_late, daemon=True).start()

    graph = {
        "graph_ready_timeout_sec": 3,
        "require_clock": False,
        "topics": [
            {
                "name": "/observer_test/concurrent_a",
                "type": "std_msgs/msg/String",
                "publisher_match": {"min_count": 1, "timeout_sec": 3},
                "subscriber_match": {"min_count": 0, "timeout_sec": 3},
            },
            {
                "name": "/observer_test/concurrent_b",
                "type": "std_msgs/msg/String",
                "publisher_match": {"min_count": 1, "timeout_sec": 3},
                "subscriber_match": {"min_count": 0, "timeout_sec": 3},
            },
        ],
        "services": [],
        "actions": [],
    }
    started = time.monotonic()
    result = observe_ros_graph(graph, wall_timeout_sec=3)
    elapsed = time.monotonic() - started
    assert result.ok, result.message
    assert result.observed["topics"]["/observer_test/concurrent_a"]["publishers"] >= 1
    assert result.observed["topics"]["/observer_test/concurrent_b"]["publishers"] >= 1
    assert elapsed < 2.5


def test_rclpy_missing_raises_observer_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "rclpy":
            raise ImportError("simulated missing rclpy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    graph = _topic_graph("/observer_test/x", pub_min=0, sub_min=0)
    with pytest.raises(RosObserverError):
        observe_ros_graph(graph, wall_timeout_sec=1)

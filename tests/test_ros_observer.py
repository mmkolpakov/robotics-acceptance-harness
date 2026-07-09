from __future__ import annotations

from collections.abc import Iterator

import pytest

rclpy = pytest.importorskip("rclpy", reason="rclpy (ROS 2) is required for live graph checks")

from rclpy.node import Node  # noqa: E402
from std_msgs.msg import String  # noqa: E402
from std_srvs.srv import Trigger  # noqa: E402

from robotics_simulation_harness.ros_observer import (  # noqa: E402
    RosObserverError,
    observe_ros_graph,
)


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

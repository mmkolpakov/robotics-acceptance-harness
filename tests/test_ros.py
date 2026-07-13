from __future__ import annotations

from types import SimpleNamespace

import pytest

from robotics_acceptance_harness.readiness import evaluate_graph
from robotics_acceptance_harness.ros import RosGraphObserver, RosObserverError


class FakeContext:
    def __init__(self) -> None:
        self.closed = False

    def try_shutdown(self) -> None:
        self.closed = True


class FakeFuture:
    def done(self) -> bool:
        return True

    def result(self) -> object:
        return SimpleNamespace(current_state=SimpleNamespace(label="active"))


class FakeClient:
    def service_is_ready(self) -> bool:
        return True

    def call_async(self, _request: object) -> FakeFuture:
        return FakeFuture()


class FakeNode:
    def __init__(self) -> None:
        self.callbacks: dict[str, object] = {}
        self.destroyed = False

    def create_subscription(
        self,
        _message_type: object,
        topic: str,
        callback: object,
        _qos: object,
    ) -> object:
        self.callbacks[topic] = callback
        return object()

    def create_client(self, _service_type: object, _name: str) -> FakeClient:
        return FakeClient()

    def get_topic_names_and_types(self) -> list[tuple[str, list[str]]]:
        return [
            ("/camera/image", ["sensor_msgs/msg/Image"]),
            ("/clock", ["rosgraph_msgs/msg/Clock"]),
        ]

    def count_subscribers(self, name: str) -> int:
        return 2 if name == "/camera/image" else 1

    def count_publishers(self, _name: str) -> int:
        return 1

    def get_publishers_info_by_topic(self, _name: str) -> list[object]:
        return [SimpleNamespace(qos_profile="sensor-data")]

    def get_service_names_and_types(self) -> list[tuple[str, list[str]]]:
        return [("/camera/get_parameters", ["rcl_interfaces/srv/GetParameters"])]

    def count_services(self, _name: str) -> int:
        return 1

    def destroy_node(self) -> None:
        self.destroyed = True


class FakeExecutor:
    def __init__(self, *, context: FakeContext) -> None:
        self.context = context
        self.node: FakeNode | None = None

    def add_node(self, node: FakeNode) -> None:
        self.node = node

    def spin_once(self, *, timeout_sec: float) -> None:
        assert timeout_sec == 0
        assert self.node is not None
        for topic, callback in self.node.callbacks.items():
            message = (
                SimpleNamespace(clock=SimpleNamespace(sec=1, nanosec=2))
                if topic == "/clock"
                else object()
            )
            callback(message)

    def remove_node(self, node: FakeNode) -> None:
        assert node is self.node


class GetState:
    class Request:
        pass


def expected_graph() -> dict[str, object]:
    return {
        "topics": [
            {
                "name": "/camera/image",
                "type": "sensor_msgs/msg/Image",
                "min_publishers": 1,
                "min_subscribers": 1,
                "first_message_timeout_sec": 2,
                "qos_profile": "sensor_data",
            }
        ],
        "services": [
            {
                "name": "/camera/get_parameters",
                "type": "rcl_interfaces/srv/GetParameters",
                "server_required": True,
            }
        ],
        "actions": [
            {
                "name": "/takeoff",
                "type": "example_interfaces/action/Fibonacci",
                "server_required": True,
            }
        ],
        "lifecycle_nodes": [
            {
                "name": "/camera",
                "required_state": "active",
                "timeout_sec": 2,
                "stable_for_sec": 0,
            }
        ],
    }


def fake_modules(node: FakeNode) -> dict[str, object]:
    return {
        "rclpy": SimpleNamespace(
            init=lambda **_kwargs: None,
            create_node=lambda *_args, **_kwargs: node,
        ),
        "rclpy.action": SimpleNamespace(
            get_action_names_and_types=lambda observed_node: (
                [("/takeoff", ["example_interfaces/action/Fibonacci"])]
                if observed_node is node
                else []
            )
        ),
        "rclpy.context": SimpleNamespace(Context=FakeContext),
        "rclpy.executors": SimpleNamespace(SingleThreadedExecutor=FakeExecutor),
        "rclpy.qos": SimpleNamespace(
            qos_profile_system_default="system-default",
            qos_profile_sensor_data="sensor-data",
            qos_profile_services_default="services-default",
            qos_profile_parameters="parameters",
            qos_profile_clock="clock",
            QoSCompatibility=SimpleNamespace(ERROR="error"),
            qos_check_compatible=lambda *_args: ("ok", ""),
        ),
        "rosidl_runtime_py.utilities": SimpleNamespace(get_message=lambda name: name),
        "lifecycle_msgs.srv": SimpleNamespace(GetState=GetState),
        "rosgraph_msgs.msg": SimpleNamespace(Clock=object),
    }


def test_ros_observer_fails_clearly_outside_ros_runtime() -> None:
    def missing_module(name: str) -> object:
        raise ModuleNotFoundError(name)

    with pytest.raises(RosObserverError, match="must be available"):
        RosGraphObserver(
            {"topics": [], "services": [], "actions": [], "lifecycle_nodes": []},
            observe_clock=True,
            module_loader=missing_module,
        )


def test_ros_observer_reports_graph_clock_and_lifecycle_without_writing() -> None:
    node = FakeNode()
    modules = fake_modules(node)
    observer = RosGraphObserver(
        expected_graph(),
        observe_clock=True,
        module_loader=modules.__getitem__,
    )

    observer.snapshot()
    snapshot = observer.snapshot()

    assert evaluate_graph(expected_graph(), snapshot) == ()
    assert snapshot.topics["/camera/image"].subscribers == 1
    assert snapshot.lifecycle_nodes["/camera"].state == "active"
    assert observer.clock_samples[-1].source_time_ns == 1_000_000_002
    observer.close()
    observer.close()
    assert node.destroyed
    with pytest.raises(RosObserverError, match="closed"):
        observer.snapshot()


def test_ros_observer_context_manager_detaches() -> None:
    node = FakeNode()
    modules = fake_modules(node)

    with RosGraphObserver(
        expected_graph(),
        observe_clock=False,
        module_loader=modules.__getitem__,
    ) as observer:
        observer.snapshot()

    assert node.destroyed


def test_ros_observer_queries_forbidden_names_without_subscribing() -> None:
    node = FakeNode()
    modules = fake_modules(node)
    observer = RosGraphObserver(
        expected_graph(),
        forbidden_graph={
            "topics": ["/cmd_vel"],
            "services": ["/arm"],
            "actions": ["/land"],
        },
        observe_clock=False,
        module_loader=modules.__getitem__,
    )

    snapshot = observer.snapshot()

    assert snapshot.topics["/cmd_vel"].publishers == 1
    assert snapshot.services["/arm"].servers == 1
    assert snapshot.actions["/land"].servers == 0
    assert "/cmd_vel" not in node.callbacks
    observer.close()

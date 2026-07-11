from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from time import monotonic_ns
from typing import Any

from robotics_acceptance_harness.readiness import (
    EndpointObservation,
    GraphSnapshot,
    LifecycleObservation,
    TopicObservation,
)
from robotics_acceptance_harness.timing import ClockSample


class RosObserverError(RuntimeError):
    """Raised when the read-only ROS observer cannot be initialized or queried."""


@dataclass(slots=True)
class _LifecycleTracker:
    client: Any
    request_type: Any
    future: Any = None
    observation: LifecycleObservation | None = None


class RosGraphObserver:
    """Read-only rclpy observer attached to an already running ROS domain."""

    def __init__(
        self,
        expected_graph: Mapping[str, Any],
        *,
        observe_clock: bool,
        node_name: str = "robotics_acceptance_observer",
        module_loader: Callable[[str], Any] = import_module,
    ) -> None:
        try:
            self._rclpy = module_loader("rclpy")
            actions = module_loader("rclpy.action")
            context_module = module_loader("rclpy.context")
            executor_module = module_loader("rclpy.executors")
            self._qos = module_loader("rclpy.qos")
            utilities = module_loader("rosidl_runtime_py.utilities")
            lifecycle_services = module_loader("lifecycle_msgs.srv")
            clock_messages = module_loader("rosgraph_msgs.msg")
        except ModuleNotFoundError as error:
            raise RosObserverError(
                "rclpy, rosidl_runtime_py, lifecycle_msgs, and rosgraph_msgs "
                "must be available in the ROS runtime"
            ) from error

        self._expected_graph = expected_graph
        self._context = context_module.Context()
        self._rclpy.init(args=None, context=self._context)
        try:
            self._node = self._rclpy.create_node(
                node_name,
                context=self._context,
                enable_rosout=False,
                start_parameter_services=False,
            )
            self._executor = executor_module.SingleThreadedExecutor(context=self._context)
            self._executor.add_node(self._node)
            self._subscriptions: list[Any] = []
            self._own_subscription_counts: dict[str, int] = {}
            self._first_messages: dict[str, int] = {}
            self._topic_qos: dict[str, Any] = {}
            self._clock_samples: list[ClockSample] = []
            self._closed = False
            self._get_message = utilities.get_message
            self._get_state_type = lifecycle_services.GetState
            self._clock_type = clock_messages.Clock
            self._get_action_names_and_types = actions.get_action_names_and_types
            self._lifecycle: dict[str, _LifecycleTracker] = {}
            self._configure_topics(observe_clock)
            self._configure_lifecycle()
        except Exception:
            self._context.try_shutdown()
            raise

    @property
    def clock_samples(self) -> tuple[ClockSample, ...]:
        return tuple(self._clock_samples)

    def _qos_profile(self, name: str) -> Any:
        profiles = {
            "system_default": self._qos.qos_profile_system_default,
            "sensor_data": self._qos.qos_profile_sensor_data,
            "services_default": self._qos.qos_profile_services_default,
            "parameters": self._qos.qos_profile_parameters,
        }
        return profiles[name]

    def _message_callback(self, topic: str) -> Callable[[Any], None]:
        def callback(_message: Any) -> None:
            self._first_messages.setdefault(topic, monotonic_ns())

        return callback

    def _clock_callback(self, message: Any) -> None:
        observed_at_ns = monotonic_ns()
        self._first_messages.setdefault("/clock", observed_at_ns)
        source_time_ns = int(message.clock.sec) * 1_000_000_000 + int(message.clock.nanosec)
        self._clock_samples.append(ClockSample(observed_at_ns, source_time_ns))

    def _subscribe(self, topic: str, message_type: Any, qos_profile: Any) -> None:
        callback = self._clock_callback if topic == "/clock" else self._message_callback(topic)
        subscription = self._node.create_subscription(
            message_type,
            topic,
            callback,
            qos_profile,
        )
        self._subscriptions.append(subscription)
        self._own_subscription_counts[topic] = self._own_subscription_counts.get(topic, 0) + 1
        self._topic_qos[topic] = qos_profile

    def _configure_topics(self, observe_clock: bool) -> None:
        for expected in self._expected_graph["topics"]:
            topic = str(expected["name"])
            message_type = self._get_message(str(expected["type"]))
            profile_name = str(expected.get("qos_profile", "system_default"))
            self._subscribe(topic, message_type, self._qos_profile(profile_name))
        if observe_clock and "/clock" not in self._own_subscription_counts:
            self._subscribe("/clock", self._clock_type, self._qos.qos_profile_clock)

    def _configure_lifecycle(self) -> None:
        for expected in self._expected_graph["lifecycle_nodes"]:
            name = str(expected["name"])
            service_name = f"{name.rstrip('/')}/get_state"
            client = self._node.create_client(self._get_state_type, service_name)
            self._lifecycle[name] = _LifecycleTracker(client, self._get_state_type.Request)

    def _poll_lifecycle(self, observed_at_ns: int) -> None:
        for tracker in self._lifecycle.values():
            if tracker.future is not None and tracker.future.done():
                try:
                    response = tracker.future.result()
                    tracker.observation = LifecycleObservation(
                        state=str(response.current_state.label).lower(),
                        observed_at_ns=observed_at_ns,
                    )
                except Exception:
                    tracker.observation = None
                tracker.future = None
            if tracker.future is None and tracker.client.service_is_ready():
                tracker.future = tracker.client.call_async(tracker.request_type())

    def _qos_compatible(self, topic: str) -> bool:
        profile = self._topic_qos[topic]
        publisher_info = self._node.get_publishers_info_by_topic(topic)
        error = self._qos.QoSCompatibility.ERROR
        return all(
            self._qos.qos_check_compatible(info.qos_profile, profile)[0] != error
            for info in publisher_info
        )

    def snapshot(self) -> GraphSnapshot:
        if self._closed:
            raise RosObserverError("observer is closed")
        self._executor.spin_once(timeout_sec=0.0)
        observed_at_ns = monotonic_ns()
        self._poll_lifecycle(observed_at_ns)

        topic_types = dict(self._node.get_topic_names_and_types())
        topics: dict[str, TopicObservation] = {}
        for expected in self._expected_graph["topics"]:
            name = str(expected["name"])
            subscribers = max(
                0,
                self._node.count_subscribers(name) - self._own_subscription_counts.get(name, 0),
            )
            topics[name] = TopicObservation(
                types=tuple(topic_types.get(name, ())),
                publishers=self._node.count_publishers(name),
                subscribers=subscribers,
                first_message_at_ns=self._first_messages.get(name),
                qos_compatible=self._qos_compatible(name),
            )

        service_types = dict(self._node.get_service_names_and_types())
        services = {
            str(expected["name"]): EndpointObservation(
                types=tuple(service_types.get(str(expected["name"]), ())),
                servers=self._node.count_services(str(expected["name"])),
            )
            for expected in self._expected_graph["services"]
        }
        action_types = dict(self._get_action_names_and_types(self._node))
        actions = {
            str(expected["name"]): EndpointObservation(
                types=tuple(action_types.get(str(expected["name"]), ())),
                servers=int(str(expected["name"]) in action_types),
            )
            for expected in self._expected_graph["actions"]
        }
        lifecycle = {
            name: tracker.observation
            for name, tracker in self._lifecycle.items()
            if tracker.observation is not None
        }
        return GraphSnapshot(
            observed_at_ns=observed_at_ns,
            topics=topics,
            services=services,
            actions=actions,
            lifecycle_nodes=lifecycle,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.remove_node(self._node)
        self._node.destroy_node()
        self._context.try_shutdown()

    def __enter__(self) -> RosGraphObserver:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


__all__ = ["RosGraphObserver", "RosObserverError"]

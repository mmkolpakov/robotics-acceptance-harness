from __future__ import annotations

import pytest

from robotics_acceptance_harness.readiness import (
    EndpointObservation,
    GraphReadinessTimeout,
    GraphSnapshot,
    LifecycleObservation,
    TopicObservation,
    evaluate_graph,
    wait_for_readiness,
)


def expected_graph() -> dict[str, object]:
    return {
        "topics": [
            {
                "name": "/camera/image",
                "type": "sensor_msgs/msg/Image",
                "min_publishers": 1,
                "min_subscribers": 1,
                "first_message_timeout_sec": 5,
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
        "lifecycle_nodes": [],
    }


def ready_snapshot() -> GraphSnapshot:
    return GraphSnapshot(
        observed_at_ns=1,
        topics={
            "/camera/image": TopicObservation(
                types=("sensor_msgs/msg/Image",),
                publishers=1,
                subscribers=1,
                first_message_at_ns=1,
            )
        },
        services={
            "/camera/get_parameters": EndpointObservation(
                types=("rcl_interfaces/srv/GetParameters",),
                servers=1,
            )
        },
        actions={
            "/takeoff": EndpointObservation(
                types=("example_interfaces/action/Fibonacci",),
                servers=1,
            )
        },
    )


def test_ready_graph_has_no_issues() -> None:
    assert evaluate_graph(expected_graph(), ready_snapshot()) == ()


def test_missing_and_mismatched_endpoints_report_contract_paths() -> None:
    snapshot = GraphSnapshot(
        observed_at_ns=1,
        topics={
            "/camera/image": TopicObservation(
                types=("sensor_msgs/msg/CompressedImage",),
                publishers=0,
                subscribers=0,
            )
        },
    )

    issues = evaluate_graph(expected_graph(), snapshot)
    paths = {issue.json_path for issue in issues}

    assert "$.expected_ros_graph.topics[0].type" in paths
    assert "$.expected_ros_graph.topics[0].min_publishers" in paths
    assert "$.expected_ros_graph.topics[0].min_subscribers" in paths
    assert "$.expected_ros_graph.services[0]" in paths
    assert "$.expected_ros_graph.actions[0]" in paths


def test_graph_snapshot_copies_input_mappings() -> None:
    topics = {"/clock": TopicObservation(("rosgraph_msgs/msg/Clock",), 1, 0)}
    snapshot = GraphSnapshot(observed_at_ns=1, topics=topics)
    topics.clear()
    assert "/clock" in snapshot.topics


def test_managed_node_must_be_active() -> None:
    expected = expected_graph()
    expected["lifecycle_nodes"] = [
        {
            "name": "/camera",
            "required_state": "active",
            "timeout_sec": 10,
            "stable_for_sec": 1,
        }
    ]
    snapshot = ready_snapshot()
    inactive = GraphSnapshot(
        observed_at_ns=snapshot.observed_at_ns,
        topics=snapshot.topics,
        services=snapshot.services,
        actions=snapshot.actions,
        lifecycle_nodes={
            "/camera": LifecycleObservation(state="inactive", observed_at_ns=1),
        },
    )

    issues = evaluate_graph(expected, inactive)
    assert [issue.json_path for issue in issues] == [
        "$.expected_ros_graph.lifecycle_nodes[0].required_state"
    ]


def test_missing_managed_node_state_is_not_ready() -> None:
    expected = expected_graph()
    expected["lifecycle_nodes"] = [
        {
            "name": "/camera",
            "required_state": "active",
            "timeout_sec": 10,
            "stable_for_sec": 1,
        }
    ]
    issues = evaluate_graph(expected, ready_snapshot())
    assert issues[0].json_path == "$.expected_ros_graph.lifecycle_nodes[0]"


def test_first_message_and_qos_match_are_required() -> None:
    snapshot = ready_snapshot()
    topic = snapshot.topics["/camera/image"]
    not_ready = GraphSnapshot(
        observed_at_ns=1,
        topics={
            "/camera/image": TopicObservation(
                types=topic.types,
                publishers=topic.publishers,
                subscribers=topic.subscribers,
                first_message_at_ns=None,
                qos_compatible=False,
            )
        },
        services=snapshot.services,
        actions=snapshot.actions,
    )

    paths = {issue.json_path for issue in evaluate_graph(expected_graph(), not_ready)}
    assert "$.expected_ros_graph.topics[0].qos_profile" in paths
    assert "$.expected_ros_graph.topics[0].first_message_timeout_sec" in paths


class FakeObserver:
    def __init__(self, snapshots: list[GraphSnapshot]) -> None:
        self.snapshots = snapshots
        self.index = 0

    def snapshot(self) -> GraphSnapshot:
        snapshot = self.snapshots[min(self.index, len(self.snapshots) - 1)]
        self.index += 1
        return snapshot

    def close(self) -> None:
        return None


class FakeTime:
    def __init__(self) -> None:
        self.value_ns = 0

    def now_ns(self) -> int:
        return self.value_ns

    def sleep(self, seconds: float) -> None:
        self.value_ns += int(seconds * 1_000_000_000)


def test_readiness_requires_an_uninterrupted_stability_window() -> None:
    ready = ready_snapshot()
    missing = GraphSnapshot(observed_at_ns=2)
    time = FakeTime()
    observer = FakeObserver([ready, missing, ready, ready, ready])

    result = wait_for_readiness(
        expected_graph(),
        observer,
        timeout_sec=5,
        stable_for_sec=2,
        poll_interval_sec=1,
        now_ns=time.now_ns,
        sleep_fn=time.sleep,
    )

    assert result.first_ready_at_ns == 2_000_000_000
    assert result.stable_for_sec == 2


def test_readiness_timeout_reports_last_contract_issues() -> None:
    time = FakeTime()
    observer = FakeObserver([GraphSnapshot(observed_at_ns=0)])

    with pytest.raises(GraphReadinessTimeout) as caught:
        wait_for_readiness(
            expected_graph(),
            observer,
            timeout_sec=2,
            stable_for_sec=1,
            poll_interval_sec=1,
            now_ns=time.now_ns,
            sleep_fn=time.sleep,
        )

    assert caught.value.issues
    assert caught.value.issues[0].json_path.startswith("$.expected_ros_graph")

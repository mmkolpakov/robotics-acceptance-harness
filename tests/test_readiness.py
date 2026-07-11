from __future__ import annotations

from robotics_acceptance_harness.readiness import (
    EndpointObservation,
    GraphSnapshot,
    TopicObservation,
    evaluate_graph,
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

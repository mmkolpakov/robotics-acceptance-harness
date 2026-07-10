"""Example: wait for a real ROS 2 graph to become ready with
`launch_testing_ros.WaitForTopics`. This starts the smallest possible real
(non-simulated) ROS 2 graph -- the clock publisher fixture in
`examples/generic/rclpy_clock_publisher.py` -- and waits for it with the
upstream helper.

Run inside a ROS 2 Jazzy environment with:
    source /opt/ros/jazzy/setup.bash
    python -m pytest examples/launch_testing/test_clock_graph_ready.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import launch
import launch.actions
import launch_testing.actions
import launch_testing.markers
import pytest
from launch_testing_ros import WaitForTopics
from rosgraph_msgs.msg import Clock

CLOCK_PUBLISHER = str(Path(__file__).resolve().parents[1] / "generic" / "rclpy_clock_publisher.py")


@pytest.mark.launch_test
@launch_testing.markers.keep_alive
def generate_test_description() -> launch.LaunchDescription:
    return launch.LaunchDescription(
        [
            launch.actions.ExecuteProcess(
                cmd=[sys.executable, CLOCK_PUBLISHER, "30"],
                name="clock_publisher",
            ),
            launch_testing.actions.ReadyToTest(),
        ]
    )


class TestClockGraphReady(unittest.TestCase):
    def test_clock_topic_is_published(self) -> None:
        with WaitForTopics([("/clock", Clock)], timeout=15.0):
            pass

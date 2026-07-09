#!/usr/bin/env python3
"""Minimal rclpy publisher used as a real (non-simulated) ROS graph fixture.

This is intentionally not a Gazebo/robot simulation: it is the smallest
possible live ROS 2 graph a harness `run` can observe with `rclpy`, so the
harness's own end-to-end pipeline exercises a real publisher/subscriber
match instead of a fake pass.
"""

from __future__ import annotations

import sys
import time

import rclpy
from builtin_interfaces.msg import Time
from rclpy.node import Node
from rosgraph_msgs.msg import Clock


def main() -> int:
    duration_sec = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    rclpy.init()
    node = Node("harness_example_clock_publisher")
    publisher = node.create_publisher(Clock, "/clock", 10)
    deadline = time.monotonic() + duration_sec
    elapsed = 0.0
    try:
        while time.monotonic() < deadline:
            message = Clock()
            seconds = int(elapsed)
            message.clock = Time(sec=seconds, nanosec=int((elapsed - seconds) * 1e9))
            publisher.publish(message)
            elapsed += 0.1
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

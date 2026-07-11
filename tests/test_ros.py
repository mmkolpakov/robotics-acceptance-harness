from __future__ import annotations

import pytest

from robotics_acceptance_harness.ros import RosGraphObserver, RosObserverError


def test_ros_observer_fails_clearly_outside_ros_runtime() -> None:
    def missing_module(name: str) -> object:
        raise ModuleNotFoundError(name)

    with pytest.raises(RosObserverError, match="must be available"):
        RosGraphObserver(
            {"topics": [], "services": [], "actions": [], "lifecycle_nodes": []},
            observe_clock=True,
            module_loader=missing_module,
        )

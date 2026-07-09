from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LaunchPlan:
    command: list[str]
    entrypoint: str


class LaunchError(ValueError):
    pass


def build_launch_plan(scenario: dict[str, Any]) -> LaunchPlan:
    launch = scenario["launch"]
    entrypoint = launch["entrypoint"]
    package = launch["package"]
    file_name = launch.get("file")
    arguments = list(launch.get("arguments") or [])

    if entrypoint == "external_command":
        command = [package, *arguments]
        if file_name:
            command.extend([file_name])
        return LaunchPlan(command=command, entrypoint=entrypoint)

    if entrypoint == "docker_compose":
        if not file_name:
            raise LaunchError("docker_compose launch requires file")
        # Prefer explicit compose verbs from scenario arguments (run/up/...).
        # Default to `up --abort-on-container-exit` only when arguments omit a verb.
        compose_verbs = {"up", "run", "exec", "build", "pull", "config", "down", "ps", "logs"}
        if arguments and arguments[0] in compose_verbs:
            command = ["docker", "compose", "-f", file_name, *arguments]
        else:
            command = [
                "docker",
                "compose",
                "-f",
                file_name,
                "up",
                "--abort-on-container-exit",
                *arguments,
            ]
        return LaunchPlan(command=command, entrypoint=entrypoint)

    if entrypoint == "ros2_launch":
        if not file_name:
            raise LaunchError("ros2_launch requires file")
        command = ["ros2", "launch", package, file_name, *arguments]
        return LaunchPlan(command=command, entrypoint=entrypoint)

    raise LaunchError(f"unsupported launch entrypoint: {entrypoint}")

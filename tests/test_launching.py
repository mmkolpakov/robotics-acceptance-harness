from __future__ import annotations

from robotics_simulation_harness.launching import build_launch_plan


def test_docker_compose_run_verb_is_preserved() -> None:
    plan = build_launch_plan(
        {
            "launch": {
                "entrypoint": "docker_compose",
                "package": "docker",
                "file": "compose.yaml",
                "arguments": ["run", "--rm", "--no-deps", "simulation"],
            }
        }
    )
    assert plan.command == [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "run",
        "--rm",
        "--no-deps",
        "simulation",
    ]


def test_docker_compose_defaults_to_up() -> None:
    plan = build_launch_plan(
        {
            "launch": {
                "entrypoint": "docker_compose",
                "package": "docker",
                "file": "compose.yaml",
                "arguments": ["simulation"],
            }
        }
    )
    assert plan.command[:6] == [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "up",
        "--abort-on-container-exit",
    ]

# robotics-simulation-harness

Thin command-line harness for resolving robotics simulation scenarios, enforcing
execution guards, supervising process trees, observing ROS graph readiness when
available, and writing evidence manifests.

The repository is domain-neutral. It does not contain product scenarios, robot
descriptions, scene layouts, trained models, or private acceptance data.

## Baseline

| Tool | Version |
| --- | --- |
| Package | 0.2.0 |
| Python | 3.10+ locally, 3.12 in CI |
| jsonschema | 4.26.0 |
| ruamel.yaml | 0.19.1 |
| rich | 14.3.0 |
| pytest | 9.0.2 |
| ruff | 0.15.0 |
| yamllint | 1.38.0 |

## Quickstart

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ../robotics-runtime-contracts -e . -r requirements-dev.txt
make RUN_ID=local e2e
```

## Main Commands

```bash
robotics-harness doctor
robotics-harness scenario resolve --composition examples/generic/composition.yaml --output runs/local/resolved-scenario.json --trace runs/local/resolution-trace.json
robotics-harness run --scenario runs/local/resolved-scenario.json --evidence runs/local/evidence-manifest.json --run-id local
robotics-harness status --run-id local
robotics-harness logs --run-id local
robotics-harness stop --run-id local
```

`run` validates the scenario against `robotics-runtime-contracts`, enforces the
simulation-only execution guard, launches the configured entrypoint through a
process group runner, and writes evidence under `runs/<run_id>/`.

`run --dry-run` validates and writes evidence without process execution.
Foundation CI may set `ROBOTICS_SKIP_ROS_OBSERVER=1` when `rclpy` is unavailable
on the runner image.

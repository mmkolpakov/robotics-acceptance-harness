# robotics-simulation-harness

A `pytest` plugin providing one thing: a simulation-only **execution guard**
for robotics test suites. Everything this repository used to do by hand
(scenario resolution/composition, process supervision, ROS graph polling,
evidence writing and signing) is now the job of an industry-standard tool,
adopted directly by the consuming test suite instead of re-implemented here:

| Old harness responsibility | Standard replacement |
| --- | --- |
| `cli.py` scenario runner | `pytest` itself |
| `process.py` process-group supervision | `pytest-docker` (container lifecycle) |
| `registry.py` PID files | Docker/pytest-docker process isolation |
| `signal_coordinator.py` SIGTERM/SIGINT handling | native `pytest` + Docker signal handling |
| `resolver.py` YAML composition/patching | `Hydra` (OmegaConf) config groups and overlays |
| `ros_observer.py` ROS graph polling | `launch_testing_ros.WaitForTopics` |
| `evidence.py` custom evidence JSON + Cosign signing | `pytest --junitxml` + SLSA Provenance (`slsa-github-generator`) |
| `guard.py` execution guard | **kept** -- rewritten as this `pytest` plugin |

The repository is domain-neutral. It does not contain product scenarios, robot
descriptions, scene layouts, trained models, or private acceptance data.

## Baseline

| Tool | Version |
| --- | --- |
| Package | 0.3.0 |
| Python | 3.10+ locally, 3.12 in CI |
| pytest | 9.0.2 |
| pytest-docker | 3.2.5 |
| ruff | 0.15.0 |
| yamllint | 1.38.0 |
| hydra-core (example) | 1.3.4 |
| omegaconf (example) | 2.3.1 |

## Quickstart

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e . -r requirements-dev.txt
make ci
```

## Using the plugin

Installing this package registers a `pytest11` plugin
(`robotics-execution-guard`) automatically -- no `-p` flag needed. It adds:

- A `robotics_scenario` fixture. Override it (per test, class, or module) to
  return a mapping with `target_environment` and
  `safety.execution_guard.allow_physical_actuation` -- typically composed
  with Hydra: `OmegaConf.to_container(cfg, resolve=True)["scenario"]`.
- An autouse `robotics_execution_guard` fixture that calls
  `enforce_execution_guard(robotics_scenario)` before every test and fails
  the test (as a setup error, fail-closed) unless the scenario is
  `target_environment: simulation` with `allow_physical_actuation: false`.
- A `robotics_physical_actuation` marker and a
  `--robotics-allow-physical-actuation` CLI flag. A test that legitimately
  needs to target real hardware must carry **both** the marker and the flag
  must be passed on the command line; either alone still fails closed.

See `examples/hydra/test_guard_with_hydra.py` for a full Hydra
compose-API integration, and `examples/launch_testing/test_clock_graph_ready.py`
for the standard `launch_testing_ros.WaitForTopics` pattern that replaced the
old bespoke ROS graph poller.

## Main commands

```bash
make validate            # yamllint
make lint                # ruff
make test                # plugin unit/integration tests, writes artifacts/reports/results.xml
make example-hydra       # Hydra-composed-scenario example (needs hydra-core/omegaconf)
make example-launch-testing  # launch_testing_ros example (needs a ROS 2 Jazzy environment)
make ci                   # validate + lint + test
```

CI additionally hashes `results.xml` and calls
`slsa-framework/slsa-github-generator`'s generic workflow to produce a
signed SLSA Provenance attestation for the test report -- the de-facto 2026
evidence standard, replacing the old repository-local Cosign-signed
`evidence-manifest.json`.

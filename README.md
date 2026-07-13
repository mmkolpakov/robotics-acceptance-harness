# Robotics Acceptance Harness

[![CI](https://github.com/mmkolpakov/robotics-acceptance-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/mmkolpakov/robotics-acceptance-harness/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mmkolpakov/robotics-acceptance-harness)](https://github.com/mmkolpakov/robotics-acceptance-harness/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Attach-only acceptance observation for an already running ROS 2 execution.

The harness validates versioned execution documents, waits for the declared ROS
graph and lifecycle states, evaluates OpenTelemetry metrics and timing, verifies
finalized evidence, and writes a contract-valid result plus JUnit XML. It does
not start containers, launch nodes, change lifecycle state, control a simulator,
verify signatures, or send commands to physical equipment.

## Supported Baseline

| Component | Baseline |
| --- | --- |
| Python | 3.12 and 3.13 |
| Contracts | `robotics-runtime-contracts` 0.5.0 |
| Canonical documents | scenario v3, runtime v3, result v3 |
| Compatibility input | v1 standalone scenario; v2 simulation bundle |
| ROS observation | ROS 2 Jazzy with `rclpy` and declared message packages |
| Metrics | newline-delimited OTLP JSON from the Collector file exporter |

`explain` needs only Python. `verify` runs in a ROS-enabled environment and
joins the existing `ROS_DOMAIN_ID`.

## Install

```bash
python -m pip install \
  https://github.com/mmkolpakov/robotics-acceptance-harness/releases/download/v0.6.0/robotics_acceptance_harness-0.6.0-py3-none-any.whl
robotics-acceptance --version
```

Use the acceptance-observer image from `robotics-runtime-infra` when ROS 2
Jazzy packages are required. A plain Python environment is sufficient for
`explain` and the pytest plugin.

## Quick Start

From a checkout:

```bash
uv sync --locked
uv run robotics-acceptance explain \
  --scenario tests/fixtures/v3/simulation.yaml \
  --runtime tests/fixtures/v3/runtime.yaml
```

This validates the bundle and prints its execution mode, workload, graph size,
evidence policy, and content digests without connecting to ROS.

## Verify an Execution

Start the runtime, recorder, and OpenTelemetry Collector outside the harness,
then attach the observer:

```bash
robotics-acceptance verify \
  --scenario /run/robotics/scenario.yaml \
  --runtime /run/robotics/runtime-manifest.json \
  --evidence-index /run/robotics/evidence-index.json \
  --otel-metrics /run/robotics/metrics.otlp.json \
  --output /run/robotics/results
```

The command exits `0` for `passed`, `1` for a completed failed verdict, and `2`
for invalid input or an observation error. Outputs are written atomically:

```text
/run/robotics/results/acceptance-result.json
/run/robotics/results/junit.xml
```

The OTLP file is accepted only when the finalized evidence index covers its
exact path, media type, size, and SHA-256 digest.

## Inputs

| Input | Required | Contract |
| --- | --- | --- |
| Scenario | Always | `acceptance-scenario.v3` |
| Runtime manifest | v3 scenario | `runtime-manifest.v3` |
| Model manifest | Inference workload | `model-artifact-manifest.v1` |
| Dataset manifest | MCAP playback | `dataset-manifest.v1` |
| Execution permit | HIL and real target | `execution-permit.v2` JSON |
| Verification record | HIL and real target | `execution-verification.v1` |
| Evidence index | `verify` | `evidence-index.v1` |
| Metrics | Physical observation and metric assertions | OTLP JSON |

Local domain extensions remain digest-pinned and local:

```bash
robotics-acceptance explain \
  --scenario scenario.yaml \
  --runtime runtime.json \
  --extension-schema org.example.sorting=sorting-extension.schema.json
```

Extensions cannot override common safety, time, transport, or evidence rules.

## Execution Scope

| Target | Supported verdict scope |
| --- | --- |
| Simulation | Real-time, stepped, and MCAP playback observation |
| HIL | Read-only observation with `physical_effect: none` |
| Real robot | Read-only observation with `physical_effect: observation` |

Physical actuation is outside version 0.6. The external infrastructure must
verify two signatures and policy authorization before it creates the
`execution-verification.v1` record. The harness then cross-checks the permit,
verification, runtime image, target identity, hardware scope, policy digest,
and validity interval. Hardware support is claimed only by the runtime's
qualification matrix, not by installing this Python package.

## Safety Observation

For v3, every forbidden command topic, service, and action is observed across
both graph readiness and the complete measurement window. The harness does not
subscribe to forbidden-only topics. Any publisher or server, including a
transient one, produces a failed result and JUnit test.

For each expected topic, the harness checks type, publisher and subscriber
counts, QoS compatibility, and first-message deadline. Services and actions
require a server. Managed nodes must remain in their required state for the
declared stability window. The observer never requests a lifecycle transition.

## Hardware Timing

Physical observation requires aligned OTLP gauge points at each collection
timestamp:

| Metric | Unit |
| --- | --- |
| `robotics.hardware.clock.offset` | `ms` |
| `robotics.hardware.clock.drift` | `ppm` |
| `robotics.hardware.message.age` | `ms` |
| `robotics.hardware.clock.monotonic` | `1` |

Every point carries string attributes `robotics.clock.sync_protocol` and
`robotics.clock.source`. Units, metadata, sample alignment, protocol, clock
offset, drift, message age, and monotonicity are checked fail-closed.

## Pytest Plugin

Project-owned simulation tests can consume validated documents directly:

```bash
uv run pytest \
  --robotics-scenario scenario.yaml \
  --robotics-runtime runtime.json
```

Use `robotics_bundle` for the cross-checked bundle or `robotics_scenario` for
the immutable scenario mapping. The plugin does not authorize physical tests.

## Development

```bash
uv sync --locked --all-groups
uv run pre-commit run --all-files
uv run coverage run --branch -m pytest \
  --robotics-scenario tests/fixtures/simulation.yaml
uv run coverage report --fail-under=80
uv build --no-sources
```

Semgrep enforces the attach-only boundary and tests its own policy rules. See
[the 0.5 to 0.6 migration guide](docs/migration-v0.5-v0.6.md) for v3 adoption.
Security reports follow [SECURITY.md](SECURITY.md), contributions follow
[CONTRIBUTING.md](CONTRIBUTING.md), and the project uses the [MIT License](LICENSE).

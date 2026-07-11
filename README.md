# Robotics Acceptance Harness

[![CI](https://github.com/mmkolpakov/robotics-acceptance-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/mmkolpakov/robotics-acceptance-harness/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mmkolpakov/robotics-acceptance-harness)](https://github.com/mmkolpakov/robotics-acceptance-harness/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Attach-only acceptance observation for an already running ROS 2 system.

The harness validates versioned execution documents, waits for the declared ROS
graph and lifecycle state, evaluates timing and OpenTelemetry metrics, verifies
finalized evidence, and writes an acceptance result plus JUnit XML. It does not
start containers, launch ROS nodes, control Gazebo, change lifecycle state, or
send commands to a robot.

## Requirements

| Component | Supported baseline |
| --- | --- |
| Python | 3.12 or 3.13 |
| Contracts | `robotics-runtime-contracts` 0.4.3 |
| ROS observation | ROS 2 Jazzy with `rclpy` and the declared message packages |
| Metrics | OTLP JSON produced by the OpenTelemetry Collector file exporter |

`explain` needs only Python. `verify` runs inside a ROS-enabled environment and
joins the existing `ROS_DOMAIN_ID`.

## Install

The current release is 0.5.1. Install its attested wheel directly from the
GitHub Release:

```bash
python -m pip install \
  https://github.com/mmkolpakov/robotics-acceptance-harness/releases/download/v0.5.1/robotics_acceptance_harness-0.5.1-py3-none-any.whl
robotics-acceptance --version
```

Use the released acceptance-observer OCI image from `robotics-runtime-infra`
when `verify` needs ROS 2 Jazzy and `rclpy`. A plain Python environment is
sufficient for `explain` and the pytest plugin.

## Quick Start

From a checkout:

```bash
uv sync --locked
uv run robotics-acceptance explain \
  --scenario tests/fixtures/v2/simulation.yaml \
  --runtime tests/fixtures/v2/runtime.yaml
```

The command validates every document and prints the resolved execution mode,
workload, graph size, evidence policy, and content digests. It does not connect
to ROS.

## Verify A Run

Start the simulation, recorder, and OpenTelemetry Collector with the runtime
infrastructure or the consuming project. Then attach the observer:

```bash
robotics-acceptance verify \
  --scenario /run/robotics/scenario.yaml \
  --runtime /run/robotics/runtime-manifest.yaml \
  --evidence-index /run/robotics/evidence-index.json \
  --otel-metrics /run/robotics/metrics.json \
  --output /run/robotics/results
```

The observer waits for endpoint and lifecycle readiness, measures for the
scenario's `execution_sec`, detaches, and then waits up to `shutdown_sec` for an
atomically published evidence index. The OTLP metrics file is accepted only
when that finalized index covers its exact size and SHA-256 digest.

Outputs:

```text
/run/robotics/results/acceptance-result.json
/run/robotics/results/junit.xml
```

The command exits `0` for `passed`, `1` for a completed failed verdict, and `2`
for invalid input or an observation error.

## Inputs

| Input | When required | Contract or format |
| --- | --- | --- |
| Scenario | Always | `acceptance-scenario.v2` |
| Runtime manifest | Scenario v2 | `runtime-manifest.v1` or `.v2` |
| Model manifest | Inference workload | `model-artifact-manifest.v1` |
| Dataset manifest | MCAP playback | `dataset-manifest.v1` |
| Execution permit | Reserved for qualified physical releases | `execution-permit.v1` |
| Evidence index | `verify` | `evidence-index.v1` |
| Metrics | Metric assertions and real-time simulation | OTLP JSON, newline-delimited |

Local domain extensions are passed without network access:

```bash
robotics-acceptance explain \
  --scenario scenario.yaml \
  --runtime runtime.yaml \
  --extension-schema org.example.sorting=sorting-extension.schema.json
```

The scenario declares the extension schema's canonical ID and SHA-256 digest.
The common safety, time, transport, and evidence rules cannot be overridden.

## Readiness

For each declared topic, the harness checks the ROS type, publisher and
subscriber counts, requested QoS compatibility, and first-message deadline.
Services and actions require a discovered server. Managed nodes must report
`active` through their standard `get_state` service for the complete stability
window. The harness never requests a lifecycle transition.

The observer's own subscriptions are excluded from subscriber counts, so it
cannot satisfy the scenario merely by attaching itself.

## Execution Modes

Version 0.5 accepts simulation targets only:

| Mode | Verdict scope |
| --- | --- |
| `simulation_realtime` | Functional assertions plus real-time factor and deadline limits |
| `simulation_stepped` | Functional and deterministic assertions, not performance |
| `playback_clocked` | Open-loop evaluation against an immutable MCAP dataset |
| `hardware_realtime` | Rejected until the HIL and real-target qualification releases |

The runtime owner controls Gazebo stepping, PX4 lockstep, rosbag playback,
recording, and process shutdown. This separation keeps the measured system
visible and prevents the observer from changing the result it evaluates.

## Pytest Integration

The compatibility plugin still exposes validated documents to project-owned
tests:

```bash
uv run pytest \
  --robotics-scenario scenario.yaml \
  --robotics-runtime runtime.yaml
```

Use the `robotics_bundle` fixture for all cross-checked manifests or the
`robotics_scenario` fixture for the immutable scenario mapping. The plugin is
simulation-only in version 0.5.

## Troubleshooting

- `rclpy ... must be available`: run `verify` in the ROS Jazzy observer image,
  not in a plain Python virtual environment.
- `no message before ...`: inspect the publisher, topic type, QoS, and
  `ROS_DOMAIN_ID`; increasing the timeout should not hide an incompatible graph.
- `deadline_miss_ratio was not observed`: export
  `robotics.simulation.deadline_miss_ratio` through the Collector.
- `OTLP metrics must be a verified ... segment`: stop and flush the Collector,
  hash the final file, and publish the evidence index atomically.
- `qualified only for simulation`: HIL and real targets remain fail-closed in
  this release even when a permit document is present.

## Development

```bash
uv sync --locked --all-groups
uv run pre-commit run --all-files
uv run pytest \
  --robotics-scenario tests/fixtures/simulation.yaml
uv build
```

Semgrep enforces the attach-only API boundary and tests its own policy rules.
See [the v0.4 to v0.5 migration guide](docs/migration-v0.4-v0.5.md) before
upgrading an existing pytest integration.

Security reports follow [SECURITY.md](SECURITY.md). Contributions follow
[CONTRIBUTING.md](CONTRIBUTING.md). The project is available under the
[MIT License](LICENSE).

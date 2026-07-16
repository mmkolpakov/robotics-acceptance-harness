# Robotics Acceptance Harness

[![CI](https://github.com/mmkolpakov/robotics-acceptance-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/mmkolpakov/robotics-acceptance-harness/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mmkolpakov/robotics-acceptance-harness)](https://github.com/mmkolpakov/robotics-acceptance-harness/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Attach-only acceptance observation for an already running ROS 2 execution.

The harness validates a scenario and runtime manifest, waits for the declared
ROS graph and lifecycle states, evaluates OpenTelemetry metrics, verifies the
final evidence index, and emits a contract-valid result plus JUnit XML. It does
not start containers, launch nodes, change lifecycle states, control a
simulator, verify signatures, or send commands to physical equipment.

## Baseline

| Component | Supported baseline |
| --- | --- |
| Python | 3.12 and 3.13 |
| Contracts | `robotics-runtime-contracts` 0.6.0 |
| Documents | `acceptance-scenario.v1`, `runtime-manifest.v1`, `acceptance-result.v1` |
| ROS observation | ROS 2 Jazzy with `rclpy` and declared message packages |
| Metrics | Newline-delimited OTLP JSON from the Collector file exporter |

`explain` needs only Python. `verify` runs in a ROS-enabled environment and
joins an existing `ROS_DOMAIN_ID`. Hardware support is qualified by the runtime
infrastructure for an exact source revision, image digest, and device; installing
this package alone does not qualify a target.

## Install

```bash
python -m pip install \
  https://github.com/mmkolpakov/robotics-acceptance-harness/releases/download/v0.7.1/robotics_acceptance_harness-0.7.1-py3-none-any.whl
robotics-acceptance --version
```

Use the acceptance-observer image from `robotics-runtime-infra` when ROS 2
Jazzy packages are required. A plain Python environment is sufficient for
`explain` and the pytest plugin.

## Quick Start

```bash
uv sync --locked
uv run robotics-acceptance explain \
  --scenario tests/fixtures/simulation/scenario.yaml \
  --runtime tests/fixtures/simulation/runtime.yaml
```

The command validates and cross-checks both documents, then prints the resolved
execution mode, workload, ROS graph size, evidence policy, and content digests.

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

Exit code `0` means passed, `1` means a completed failed verdict, and `2` means
invalid input or an observation error. Outputs are written atomically:

```text
/run/robotics/results/acceptance-result.json
/run/robotics/results/junit.xml
```

The OTLP file is accepted only when the finalized evidence index covers its
exact path, media type, byte size, and SHA-256 digest.

## Inputs

| Input | Required when | Contract |
| --- | --- | --- |
| Scenario | Always | `acceptance-scenario.v1` |
| Runtime manifest | Always | `runtime-manifest.v1` |
| Model manifest | Inference workload | `model-artifact-manifest.v1` |
| Dataset manifest | MCAP playback | `dataset-manifest.v1` |
| Execution permit | HIL or real target | `execution-permit.v1` |
| Verification record | HIL or real target | `execution-verification.v1` |
| Evidence index | `verify` | `evidence-index.v1` |
| Metrics | Metric assertions or physical observation | OTLP JSON |

Local domain extensions remain explicit and digest-pinned:

```bash
robotics-acceptance explain \
  --scenario scenario.yaml \
  --runtime runtime.json \
  --extension-schema org.example.sorting=sorting-extension.schema.json
```

Extensions cannot override common safety, timing, transport, or evidence rules.

## Execution Scope

| Target | Verdict scope |
| --- | --- |
| Simulation | Real-time, stepped, and MCAP playback observation |
| HIL | Read-only observation with `physical_effect: none` |
| Real robot | Read-only observation with `physical_effect: observation` |

External infrastructure must verify two authorized signatures and evaluate the
execution policy before creating an `execution-verification.v1` record. The
harness then cross-checks the permit, verification record, runtime image,
target identity, hardware scope, policy digest, and validity interval.

Every forbidden command topic, service, and action is monitored during graph
readiness and throughout the measurement window. Any publisher or server,
including a transient one, fails the result. Expected topics are checked for
type, publisher and subscriber counts, QoS compatibility, and first-message
deadline. Managed nodes must remain in their required state for the declared
stability window; the harness never requests a lifecycle transition.

Physical observation also validates aligned OTLP measurements for clock offset,
clock drift, message age, and monotonicity, including their units, source, and
synchronization protocol.

## Pytest Plugin

Project-owned simulation tests can consume the validated bundle directly:

```bash
uv run pytest \
  --robotics-scenario scenario.yaml \
  --robotics-runtime runtime.json
```

Use `robotics_bundle` for the cross-checked bundle or `robotics_scenario` for
the immutable scenario mapping. The plugin refuses physical targets.

## Development

```bash
uv sync --locked --all-groups
uv run pre-commit run --all-files
uv run coverage run --branch -m pytest \
  --robotics-scenario tests/fixtures/simulation/scenario.yaml \
  --robotics-runtime tests/fixtures/simulation/runtime.yaml
uv run coverage report --fail-under=80
uv build --no-sources
```

Semgrep enforces the attach-only boundary and tests its policy rules. Security
reports follow [SECURITY.md](SECURITY.md), contributions follow
[CONTRIBUTING.md](CONTRIBUTING.md), and the project uses the [MIT License](LICENSE).

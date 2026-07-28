# Compatibility Policy

## Versioning

`robotics-acceptance-harness` uses Semantic Versioning. Before `1.0.0`, a minor
release may change Python APIs or CLI behavior; patch releases remain backward
compatible. The documented CLI, exit codes, pytest fixtures, and emitted
contract documents are public interfaces.

The Python distribution declares
`robotics-runtime-contracts>=0.10.0,<0.11`. Development uses the sibling checkout
through `tool.uv.sources`; published wheel metadata contains only the version
specifier. `uv build --no-sources` is the packaging gate.

## Contract Compatibility

Published schema bytes are immutable. An incompatible structural or semantic
change receives a new `schema_version`; the loader supports the old and new
versions during a documented migration window. Migration functions produce a
new document and never mutate stored evidence.

| Input or output | Accepted versions |
| --- | --- |
| Scenario | `acceptance-scenario.v1` through `acceptance-scenario.v4` |
| Runtime manifest | `runtime-manifest.v1` |
| Result | `acceptance-result.v1` through `acceptance-result.v4` |
| Run context | `acceptance-run.v1` |
| Aggregate | `acceptance-aggregate.v1`, `acceptance-aggregate.v2` |
| Evidence index | `evidence-index.v1`, `evidence-index.v2` |

Compatibility is checked per schema, not inferred from the package version.
Unknown schema identifiers fail closed.

Release `0.11.0` writes `acceptance-result.v4` for v4 run-scoped verification.
Version 4 separates RMW delivery latency from hardware clock offset while
retaining verified NDJSON trace evidence. Aggregation reads `v2` through `v4`
during the migration window; new infrastructure scenarios use `v4`.

`verify` always requires `--run-id`. The `--domain-id` and `--run-context`
options are required for `acceptance-scenario.v2` through v4; v1 verification
remains valid without them. Version 3 adds an explicit stepped-simulation skip
budget; version 4 gives delivery latency and hardware clock synchronization
separate names and policies.

Channel delivery evaluation uses the first producer span as the start of the
declared observation window. Spans crossing either boundary fail closed.
Producer message identifiers are unique correlation keys; consumer repetitions
remain measurable duplicate deliveries governed by the channel contract.

## Normative Runtime Baseline

The current contracts identify ROS 2 Jazzy, Gazebo Harmonic where simulation is
present, and zstd for compressed evidence. The harness directly requires only
Python for document-only commands; live observation additionally requires the
Jazzy `rclpy` environment and declared ROS message packages.

A different ROS distribution, simulator generation, or evidence encoding is a
new qualified baseline and requires a new schema version where a current
constant would change.

## Extensions

Local domain extensions are separate, digest-pinned schemas. They cannot replace
common safety, timing, transport, authorization, or evidence fields. Fields
that prove reusable enter the shared contract only through a versioned schema
change and compatibility tests.

## Support Window

Python 3.12 and 3.13 are tested. Security fixes are provided for the latest
tagged minor release. Older document versions remain readable for the overlap
window recorded in their migration notes.

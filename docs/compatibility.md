# Compatibility Policy

## Versioning

`robotics-acceptance-harness` uses Semantic Versioning. Before `1.0.0`, a minor
release may change Python APIs, CLI behavior, and accepted contract versions;
patch releases remain backward compatible. The documented CLI, exit codes,
pytest fixtures, and emitted documents are public interfaces.

The distribution requires `robotics-runtime-contracts>=0.15,<0.16`.
Development uses the sibling checkout through `tool.uv.sources`; published
wheel metadata contains only this version range. `uv build --no-sources` is the
packaging gate.

## Contract Baseline

| Input or output | Accepted versions |
| --- | --- |
| Scenario | `acceptance-scenario.v5`, `v4` reader |
| Runtime manifest | `runtime-manifest.v3`, `v1`/`v2` readers |
| Result | `acceptance-result.v5`, `v4` reader for aggregation |
| Run context | `acceptance-run.v1` |
| Per-domain and cross-domain aggregate | `acceptance-aggregate.v4` |
| Evidence index | `evidence-index.v3`, `v2` reader |
| Transport qualification | `transport-qualification-result.v2`; `v1` reader only with a v4 scenario |
| Campaign summary | `campaign-summary.v1` |

Unknown identifiers fail closed. Published schema bytes remain immutable; an
incompatible change receives a new identifier. Before `1.0.0`, obsolete
contract readers are removed from the current package instead of becoming a
permanent compatibility layer. Historical tags remain the archive.

`verify` requires `--scenario`, `--runtime`, `--run-id`, `--domain-id`,
`--run-context`, `--evidence-index`, `--otel-metrics`,
`--measurement-complete`, and `--output`.
Aggregation accepts v4 or v5 domain results and an optional canonical transport
qualification. A v5 scenario requires transport v2 so the clock relation cannot
be bypassed. Aggregation emits one v4 aggregate whose cross-domain verdict is
either `unevaluated` or a digest-pinned transport reference.

## Runtime Baseline

The current contracts identify ROS 2 Jazzy, Gazebo Harmonic where simulation is
present, OTLP JSON metrics, MCAP evidence, and zstd compression. Document-only
commands require Python 3.12 or 3.13; live observation also requires the Jazzy
`rclpy` environment and declared ROS message packages.

A different ROS distribution, simulator generation, or evidence encoding is a
new qualified baseline and requires a contract revision when a current constant
changes.

## Extensions

Local domain extensions are separate, digest-pinned schemas. They cannot replace
common safety, timing, transport, authorization, or evidence fields. Reusable
fields enter the shared contracts through a reviewed schema revision.

## Support

Python 3.12 and 3.13 are tested. Security fixes target the latest tagged minor
release.

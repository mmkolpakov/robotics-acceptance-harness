# Migrate from 0.5 to 0.6

Version 0.6 makes the v3 execution documents the canonical input and adds
fail-closed observation for authorized HIL and real targets. Version 0.5
simulation bundles remain accepted.

## Dependency

The harness now requires `robotics-runtime-contracts` 0.5.0. Install the
released harness wheel; its direct-reference dependency pins the matching
contracts wheel.

## Canonical simulation bundle

Change new simulation scenarios to `acceptance-scenario.v3`, add an empty
forbidden graph and use `runtime-manifest.v3`:

```yaml
schema_version: acceptance-scenario.v3
authorization: {mode: none}
forbidden_ros_graph: {topics: [], services: [], actions: []}
```

The runtime manifest uses `authorization: {mode: none}` and an empty
`physical_targets` array. Existing v2 simulation bundles need no immediate
change.

## Physical observation

HIL and real-target observation require all of the following inputs:

- `acceptance-scenario.v3`;
- `runtime-manifest.v3`;
- a UTF-8 JSON `execution-permit.v2`;
- `execution-verification.v1` produced by the external cryptographic preflight;
- a finalized `evidence-index.v1`;
- file-backed OTLP JSON referenced by that evidence index.

Pass the two authorization records explicitly:

```bash
robotics-acceptance verify \
  --scenario scenario.yaml \
  --runtime runtime-manifest.json \
  --permit execution-permit.json \
  --verification execution-verification.json \
  --evidence-index evidence-index.json \
  --otel-metrics hardware-timing.otlp.json \
  --output results
```

The harness validates and cross-checks the verified facts. It does not verify
signatures itself and does not launch, configure, or command the target.

## Hardware timing metrics

Each collection timestamp must contain the following aligned OTLP gauge points:

| Metric | Unit |
| --- | --- |
| `robotics.hardware.clock.offset` | `ms` |
| `robotics.hardware.clock.drift` | `ppm` |
| `robotics.hardware.message.age` | `ms` |
| `robotics.hardware.clock.monotonic` | `1` |

Every point must include string attributes `robotics.clock.sync_protocol` and
`robotics.clock.source`. Their values must match the scenario policy and the
source mapping in `acceptance-result.v3`.

## Result changes

Version 3 scenarios produce `acceptance-result.v3`. The result includes the
verified target identity, forbidden-interface observations, hardware timing,
and the SHA-256 digest of its OTLP evidence. A forbidden publisher or server,
or timing outside policy, produces a completed `failed` verdict and a matching
JUnit failure.

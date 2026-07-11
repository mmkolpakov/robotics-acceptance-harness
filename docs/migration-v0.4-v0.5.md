# Migrating From v0.4 to v0.5

Version 0.5 renames the distribution and primary import package, adds the
standalone observer, and adopts the version 0.4.2 runtime contracts.

## Package Names

| v0.4 | v0.5 |
| --- | --- |
| `robotics-simulation-harness` | `robotics-acceptance-harness` |
| `robotics_simulation_harness` | `robotics_acceptance_harness` |
| no console command | `robotics-acceptance` |

The old Python package remains as a compatibility import for version 0.5. New
code should import `robotics_acceptance_harness`. The old repository URL is
redirected by GitHub after the repository rename.

## Scenario v1

The pytest plugin continues to accept a fully resolved
`acceptance-scenario.v1` file:

```bash
pytest --robotics-scenario scenario-v1.yaml
```

Scenario v1 does not support runtime, model, dataset, permit, readiness, or
evidence manifests. Use scenario v2 for the standalone observer.

## Scenario v2

Pass the runtime manifest and each digest-bound optional document:

```bash
pytest \
  --robotics-scenario scenario-v2.yaml \
  --robotics-runtime runtime.yaml \
  --robotics-model model.yaml \
  --robotics-dataset dataset.yaml
```

Use `runtime-manifest.v2` with `workload.kind: none` for physics, sensor, and
transport tests that do not run a model. Do not create a placeholder model.

## Standalone Observation

Move process startup and shutdown to the runtime infrastructure. Replace any
project wrapper that launches Compose or ROS from pytest with this order:

1. Resolve and validate the scenario and manifests.
2. Start the runtime and evidence producers externally.
3. Run `robotics-acceptance verify` in the observer environment.
4. Let the runtime close recorders and publish `evidence-index.v1` atomically.
5. Consume `acceptance-result.json` and `junit.xml` in CI.

Version 0.5 refuses HIL and real-robot verification. Existing simulation-only
pytest use remains fail-closed and compatible.

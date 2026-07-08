# robotics-simulation-harness

Thin command-line harness for resolving robotics simulation scenarios, enforcing
execution guards, streaming native process logs, and writing evidence manifests.

The repository is domain-neutral. It does not contain product scenarios, robot
descriptions, scene layouts, trained models, or private acceptance data.

## Baseline

| Tool | Version |
| --- | --- |
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
python -m pip install -e . -r requirements-dev.txt
make e2e
```

## Main Commands

```bash
robotics-harness doctor
robotics-harness scenario resolve --composition examples/generic/composition.yaml --output artifacts/reports/resolved-scenario.json --trace artifacts/reports/resolution-trace.json
robotics-harness run --scenario artifacts/reports/resolved-scenario.json --evidence artifacts/reports/evidence-manifest.json --dry-run
robotics-harness status
robotics-harness logs
robotics-harness stop
```

`scenario resolve` writes both the final manifest and a trace explaining which
file changed which field. `run --dry-run` validates the execution guard and
creates an evidence manifest without starting robot processes.

Process execution helpers use process groups and signal handlers so that a
stopped harness can terminate the child process tree.

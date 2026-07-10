# robotics-simulation-harness

Small pytest plugin that accepts one resolved robotics scenario, validates it
against `acceptance-scenario.v1`, and permits test collection only for
`target_environment: simulation`.

The repository does not compose scenarios, start processes or containers,
interpret simulator logs, or manage artifacts. Those responsibilities stay in
the consuming project and its standard test tooling.

## Toolchain

| Component | Version |
| --- | --- |
| Python | 3.12 |
| Package | 0.4.0 |
| robotics-runtime-contracts | 0.3.x |
| uv | 0.11.28 |
| pytest | 9.1.1 |
| PyYAML | 6.0.x |
| ruff | 0.15.21 |

## Use

Pass a fully resolved YAML file to pytest:

```bash
uv run pytest --robotics-scenario path/to/resolved-scenario.yaml
```

The session stops before collecting tests when the option is absent, the file
is invalid, or its target is not `simulation`. The `robotics_scenario` fixture
exposes the validated scenario as a deeply immutable mapping.

## Development

```bash
uv sync --locked
uv run pre-commit run --all-files
uv run pytest --robotics-scenario tests/fixtures/simulation.yaml
uv build
```

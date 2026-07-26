# `robotics-acceptance-harness` Quality Declaration

This document follows [REP-2004](https://www.ros.org/reps/rep-2004.html). The
package currently claims **Quality Level 4**.

## Version Policy

The package uses Semantic Versioning and is currently pre-`1.0.0`. It therefore
does not claim the stable-version requirement of REP-2004 Quality Level 3.
Public interfaces and compatibility rules are listed in
[Compatibility Policy](docs/compatibility.md).

## Change Control

Changes are reviewed through pull requests. CI runs tests, coverage, Ruff,
mypy, repository hooks, package builds, and installed-wheel checks.

## Documentation and License

README documents each CLI mode and pytest integration. The repository is
licensed under MIT; copyright and authorship are recorded in [LICENSE](LICENSE)
and package metadata.

## Testing

Unit and integration tests cover document validation, graph readiness, timing,
authorization, evidence, aggregation, and trace evaluation. CI enforces branch
coverage of at least 80 percent. Ruff, mypy strict mode, Semgrep, actionlint,
YAML linting, and Markdown linting are required checks.

## Dependencies

Runtime dependencies are `junitparser`, `opentelemetry-proto`, `PyYAML`, and
`robotics-runtime-contracts`. Live ROS observation uses the qualified runtime
environment instead of declaring ROS packages as Python dependencies.

## Platform Support

Document-only commands support Python 3.12 and 3.13. Live observation is
qualified on Linux with ROS 2 Jazzy. The package does not claim every REP-2000
Tier 1 platform, which is another reason not to claim Quality Level 3.

## Security

Vulnerability reporting and the observer trust boundary are documented in
[SECURITY.md](SECURITY.md).

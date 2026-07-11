# Contributing

Open an issue before changing a public contract, safety boundary, or supported
execution mode. Keep product scenes, robot commands, model weights, and launch
orchestration in consuming repositories.

## Local Checks

```bash
uv sync --locked --all-groups
uv run pre-commit run --all-files
uv run pytest --robotics-scenario tests/fixtures/simulation.yaml
uv build
```

Every behavioral change needs a focused test. Changes to Semgrep policy need a
matching `ruleid` or `ok` example in `.semgrep/attach-only.py`. Pull requests
must pass the required `test` check and resolve all review conversations.

Use Conventional Commit subjects. Do not commit generated results, evidence,
private scenarios, credentials, or hardware identities.

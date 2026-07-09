# vendor/contracts-schemas

This is a **read-only mirror** of `robotics-runtime-contracts` schemas, used
only as a fallback when the `robotics-runtime-contracts` package is not
installed (for example: fast local iteration without cloning the sibling
repository).

`robotics-runtime-contracts` remains the single source of truth for schemas.
Whenever a package/environment providing `robotics_runtime_contracts.schema_dir()`
is importable, or `ROBOTICS_CONTRACTS_ROOT` / `ROBOTICS_CONTRACTS_SCHEMA_DIR`
is set, `schemas.py` prefers it over this vendored copy.

`CONTRACTS_REF` pins the `robotics-runtime-contracts` ref this vendored copy
must match byte-for-byte. CI enforces this with a hard vendor-sync gate: it
checks out `robotics-runtime-contracts` at that ref and diffs its `schemas/`
directory against this one, failing the build on any drift. Update both the
vendored files and `CONTRACTS_REF` together in the same pull request whenever
contracts change.

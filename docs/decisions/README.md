# Architecture Decisions

This directory uses [MADR 4.0.0](https://adr.github.io/madr/) to record accepted
decisions that constrain the acceptance harness.

| Decision | Record |
| --- | --- |
| R-1: runtime ownership | [ADR-0001](0001-runtime-owns-the-execution-environment.md) |
| R-2: platform migration | [ADR-0002](0002-requalify-platform-migrations.md) |
| R-3: compatibility baseline | [ADR-0003](0003-version-the-runtime-baseline.md) |
| R-4: multi-domain acceptance | [ADR-0004](0004-aggregate-per-domain-results.md) |
| R-5: accelerator qualification | [ADR-0005](0005-consume-qualified-accelerator-evidence.md) |
| R-6: foundation prerequisites | [ADR-0006](0006-gate-integrations-on-foundation-readiness.md) |
| R-7: schema evolution | [ADR-0007](0007-preserve-published-schema-bytes.md) |
| R-8: reference integration order | [ADR-0008](0008-onboard-reference-integrations-in-stages.md) |
| Permit identity and workload identity | [ADR-0009](0009-separate-permit-and-workload-identities.md) |

New records use monotonically increasing four-digit identifiers. Accepted
records are superseded by a new ADR, never rewritten to describe a different
decision.

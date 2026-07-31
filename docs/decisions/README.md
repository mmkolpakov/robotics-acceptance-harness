# Architecture Decisions

This directory uses [MADR 4.0.0](https://adr.github.io/madr/) to record accepted
decisions that constrain the acceptance harness.

| Decision | Record |
| --- | --- |
| R-1: runtime ownership | [ADR-0001](0001-runtime-owns-the-execution-environment.md) |
| R-4: multi-domain acceptance | [ADR-0004](0004-aggregate-per-domain-results.md) |
| R-5: accelerator qualification | [ADR-0005](0005-consume-qualified-accelerator-evidence.md) |
| Permit identity and workload identity | [ADR-0009](0009-separate-permit-and-workload-identities.md) |

New records use monotonically increasing four-digit identifiers. This directory
contains only decisions owned by the acceptance harness; repository history
retains records removed after an ownership correction.

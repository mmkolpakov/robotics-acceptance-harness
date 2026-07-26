---
status: accepted
date: 2026-07-26
---

# Version the Runtime Baseline

## Context and Problem Statement

Contract constants such as the supported ROS distribution and evidence encoding
are normative interoperability claims.

## Considered Options

* Broaden existing schemas whenever another baseline appears.
* Keep each published schema baseline fixed and introduce a new schema version.

## Decision Outcome

Chosen option: keep the baseline fixed per schema version. A second operational
baseline requires a new schema version and an explicit migration.

## Consequences

* Consumers can interpret old evidence without temporal ambiguity.
* Supporting a new baseline is visible in compatibility policy and tests.
* Schema versions do not become unbounded feature flags.

## Confirmation

Schema byte checks and cross-version fixtures verify the declared compatibility
window.

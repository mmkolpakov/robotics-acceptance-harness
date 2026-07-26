---
status: accepted
date: 2026-07-26
---

# Gate Integrations on Foundation Readiness

## Context and Problem Statement

Consumer integrations cannot compensate reliably for missing contract,
authorization, timing, or evidence invariants in the shared foundation.

## Considered Options

* Let each consumer implement missing foundation behavior.
* Complete and qualify shared prerequisites before onboarding consumers.

## Decision Outcome

Chosen option: gate integrations on versioned contracts, runtime manifests,
evidence finalization, observer safety boundaries, and executable acceptance
tests.

## Consequences

* Consumer repositories contain domain behavior rather than duplicated controls.
* Foundation changes have explicit compatibility and qualification gates.
* Integration failures can be assigned to a documented ownership boundary.

## Confirmation

The compatibility matrix and reference fixtures must pass before a baseline is
declared supported.

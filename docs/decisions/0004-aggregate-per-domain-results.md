---
status: accepted
date: 2026-07-26
---

# Aggregate Per-Domain Results

## Context and Problem Statement

Independent ROS domains cannot be observed as one complete graph by a single
observer, while one execution still needs one auditable verdict.

## Considered Options

* Bridge every domain into one observer domain.
* Observe each domain separately and aggregate contract-valid results.

## Decision Outcome

Chosen option: observe each domain separately under one immutable run context,
then aggregate the complete expected result set.

## Consequences

* A missing or duplicate domain fails aggregation.
* Domain verdicts remain independently inspectable.
* Cross-domain causality is a separate evidence-backed evaluation stage.

## Confirmation

Aggregate tests cover missing domains, duplicate result identifiers, digest
mismatches, and broken trace chains.

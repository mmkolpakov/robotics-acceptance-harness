---
status: accepted
date: 2026-07-26
---

# Requalify Platform Migrations

## Context and Problem Statement

Changing a ROS distribution, simulator generation, middleware, or target
platform can alter timing, graph discovery, QoS, and evidence behavior.

## Considered Options

* Treat platform migration as a dependency-only update.
* Require qualification evidence for the complete changed runtime.

## Decision Outcome

Chosen option: require complete runtime requalification. Compatibility is
established by observed behavior and pinned artifacts, not by package names
alone.

## Consequences

* Existing acceptance results do not qualify a new platform combination.
* Runtime manifests identify the exact qualified baseline.
* The harness remains neutral to how the runtime performs the migration.

## Confirmation

Compatibility review checks manifest values, image digests, and qualification
evidence before a new baseline is documented.

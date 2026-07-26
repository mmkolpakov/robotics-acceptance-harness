---
status: accepted
date: 2026-07-26
---

# Runtime Owns the Execution Environment

## Context and Problem Statement

Acceptance evaluation must remain independent from process orchestration and
must not acquire authority to start, stop, or control the observed system.

## Considered Options

* Let the harness orchestrate the execution.
* Keep orchestration in runtime infrastructure and make the harness attach-only.

## Decision Outcome

Chosen option: keep orchestration in runtime infrastructure. The harness accepts
validated documents, attaches to an existing ROS graph, observes evidence, and
emits results.

## Consequences

* The observer can fail without becoming a control-plane failure.
* Runtime manifests and finalized evidence form the handoff boundary.
* Startup, shutdown, simulation control, and device access remain external.

## Confirmation

Semgrep policy, negative tests, and security review enforce the attach-only API
boundary.

---
status: accepted
date: 2026-07-26
---

# Consume Qualified Accelerator Evidence

## Context and Problem Statement

Accelerator availability, provider selection, and numerical conformance depend
on the runtime image, driver, device, and model.

## Considered Options

* Detect and qualify accelerators inside the harness.
* Consume runtime facts and qualification evidence produced by the runtime.

## Decision Outcome

Chosen option: the harness consumes qualified runtime facts and evaluates
scenario assertions. It does not install drivers, select providers, or probe
devices as an orchestration step.

## Consequences

* Device-specific logic stays outside the acceptance observer.
* Silent provider fallback is represented as a runtime conformance failure.
* Qualification evidence remains tied to exact artifacts and hardware.

## Confirmation

Model and runtime manifest alignment plus evidence digest checks gate
accelerated acceptance.

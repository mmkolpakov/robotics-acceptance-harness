---
status: accepted
date: 2026-07-26
---

# Onboard Reference Integrations in Stages

## Context and Problem Statement

A foundation needs end-to-end evidence from a small integration before a more
distributed or hardware-dependent integration can be trusted.

## Considered Options

* Onboard the most complex consumer first.
* Qualify a single-domain reference, then add multi-domain and physical targets.

## Decision Outcome

Chosen option: qualify integrations in increasing order of distribution,
accelerator dependence, and physical effect.

## Consequences

* Early failures isolate contract and observer defects cheaply.
* Later stages reuse the same result and evidence interfaces.
* A reference integration proves the path without becoming product logic.

## Confirmation

Each stage has a machine-readable scenario, result, JUnit report, and pinned
evidence set before the next stage is accepted.

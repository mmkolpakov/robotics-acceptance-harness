---
status: accepted
date: 2026-07-26
---

# Preserve Published Schema Bytes

## Context and Problem Statement

Evidence and results retain schema identifiers and digests after the producing
software has changed.

## Considered Options

* Correct published schemas in place.
* Keep published bytes immutable and release a new schema version.

## Decision Outcome

Chosen option: published schema bytes are immutable. Incompatible or semantic
changes use a new schema identifier. Versions overlap only while an active
consumer requires both; historical tags retain unsupported versions.

## Consequences

* Historical artifacts remain verifiable.
* Consumers can support multiple explicit versions without guessing.
* Code fixes may change while schema bytes remain fixed.

## Confirmation

Release checks compare canonical schema bytes and run fixtures for every
supported version.

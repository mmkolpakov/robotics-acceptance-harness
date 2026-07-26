---
status: accepted
date: 2026-07-26
---

# Separate Permit and Workload Identities

## Context and Problem Statement

An execution permit authorizes a bounded action against an identified target.
A [SPIFFE SVID](https://spiffe.io/docs/latest/spiffe/concepts/) proves the
cryptographic identity of a running workload. These statements have different
issuers, lifetimes, and authorization semantics.

## Considered Options

* Treat a SPIFFE ID as the permit target identity.
* Treat the two identities as independent claims and bind them in policy.

## Decision Outcome

Chosen option: keep the identities independent. A SPIFFE SVID may authenticate
the workload presenting evidence, but it does not replace target identity,
hardware scope, operator approval, validity interval, or permitted physical
effect.

## Consequences

* Workload authentication and execution authorization can rotate independently.
* Policy may require an explicit binding between a workload ID and permit
  subject.
* The harness cross-checks validated permit facts; signature and SVID validation
  stay in the external trust boundary.

## Confirmation

Authorization tests reject mismatched target identity, scope, digest, signer
role, and validity interval. Deployment policy separately validates the SVID.

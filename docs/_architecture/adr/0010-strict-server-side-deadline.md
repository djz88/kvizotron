---
status: accepted
date: 2026-11-04
---

# ADR-0010: Strict server-side deadline and attempt time limit

## Context and Problem Statement

Competitions need fair, unambiguous cut-off times.

## Decision Drivers

* Fairness
* Clock trust
* Simplicity

## Considered Options

* Server time, accept iff server_now <= min(deadline_at, started_at + attempt_limit)
* Grace period
* Client time

## Decision Outcome

Chosen option: "Server time, accept iff server_now <= min(deadline_at, started_at + attempt_limit)", because it is strict and verifiable.

### Consequences

* Good, because late submissions rejected even if started before deadline
* Good, because runs without deadline valid until manual close
* Bad, because participants with slow connections near the deadline may lose submissions

### Confirmation

[AC-07](../acceptance-criteria.md).

## More Information

FR-10, FR-11. Times stored in UTC. Boundary-second semantics: [ADR-0025](0025-deadline-boundary-second-semantics.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)

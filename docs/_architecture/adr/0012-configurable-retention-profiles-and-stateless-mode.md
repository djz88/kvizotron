---
status: accepted
date: 2026-11-04
---

# ADR-0012: Configurable retention profiles per run, including a stateless mode

## Context and Problem Statement

Different events need different amounts of stored personal data; data minimisation is a priority.

## Decision Drivers

* Data minimisation
* Feature dependencies made explicit
* Retention cannot be bypassed

## Considered Options

* Per-run profile (none / aggregate / answers / detailed) + retention period
* Always store everything
* Never store

## Decision Outcome

Chosen option: "Per-run profile (none / aggregate / answers / detailed) + retention period", because admins pick the minimum needed and see dependencies.

### Consequences

* Good, because stateless mode shows score without persistence
* Good, because periodic anonymisation/deletion job
* Bad, because scoreboard, draws, history and exports unavailable in stateless mode
* Bad, because backups need their own retention

### Confirmation

[AC-09](../acceptance-criteria.md), [AC-14](../acceptance-criteria.md).

## More Information

FR-31, FR-33, FR-34; [../../privacy.md](../../privacy.md). Default period: [ADR-0029](0029-default-retention.md). Backups: 30 days by default. Image answers need stored answers ([ADR-0033](0033-image-answer-question-type.md)).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)

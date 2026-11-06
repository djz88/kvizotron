---
status: accepted
date: 2026-11-04
---

# ADR-0007: Restart of a competition creates a new QuizRun and keeps history

## Context and Problem Statement

Admins want to run the same quiz again with a fresh ranking (clarification 47).

## Decision Drivers

* Fresh ranking per run
* No accidental data loss
* Retention still applies

## Considered Options

* New QuizRun with empty results; optional config copy
* Reset results in place
* Clone whole quiz

## Decision Outcome

Chosen option: "New QuizRun with empty results; optional config copy", because it gives a clean ranking without deleting history.

### Consequences

* Good, because old runs viewable in admin
* Good, because new statistics, rewards, draws, scoreboard
* Bad, because history grows; relies on retention for cleanup

### Confirmation

[AC-05](../acceptance-criteria.md), [AC-14](../acceptance-criteria.md).

## More Information

FR-12, FR-30. Never copies attempts or results.

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)

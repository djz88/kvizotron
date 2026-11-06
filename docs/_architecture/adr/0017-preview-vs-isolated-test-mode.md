---
status: accepted
date: 2026-11-04
---

# ADR-0017: Preview and isolated test mode, admin chooses

## Context and Problem Statement

Admins need to try quizzes without polluting real results (clarification 46).

## Decision Drivers

* No pollution of public data
* Realistic testing option

## Considered Options

* Both preview (no writes) and test mode (flagged attempts), admin chooses
* Preview only
* Test mode only

## Decision Outcome

Chosen option: "Both preview (no writes) and test mode (flagged attempts), admin chooses", because it covers quick checks and full end-to-end tests.

### Consequences

* Good, because test attempts never in scoreboard, rewards, draws or real statistics
* Bad, because every projection must filter `test_mode`

### Confirmation

[AC-12](../acceptance-criteria.md).

## More Information

FR-13.

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)

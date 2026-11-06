---
status: accepted
date: 2026-11-04
---

# ADR-0008: Per-run scoreboard revision mode, default SEPARATE_BY_REVISION

## Context and Problem Statement

A run can span several revisions; comparing scores across revisions may be unfair (clarification 47).

## Decision Drivers

* Fairness
* Admin control
* Safe default

## Considered Options

* SEPARATE_BY_REVISION / MERGE_COMPATIBLE / LATEST_ONLY chosen per run
* Always merge
* Always separate

## Decision Outcome

Chosen option: "SEPARATE_BY_REVISION / MERGE_COMPATIBLE / LATEST_ONLY chosen per run", because admins decide consciously while the default stays safe.

### Consequences

* Good, because merging is a conscious admin decision based on the shown differences
* Bad, because it relies on the admin's judgement and can merge revisions with different scoring

### Confirmation

[AC-06](../acceptance-criteria.md).

## More Information

Merge rule, resolving [OQ-13](../open-questions.md), decided 2026-11-05. The server only requires equal
maximum points. The admin UI shows the differences between the revisions (changed questions, points,
scoring strategies) and warns that equal points do not guarantee equal difficulty. The admin decides,
and the confirmation is written to `audit_event`. This replaces the undefined "compatible scoring
metric" of the original spec.

FR-30; [../modules/domain.md](../modules/domain.md), [../plugins/results-scoreboard.md](../plugins/results-scoreboard.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)

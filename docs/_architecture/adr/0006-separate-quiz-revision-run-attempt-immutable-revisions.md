---
status: accepted
date: 2026-11-04
---

# ADR-0006: Separate Quiz, QuizRevision, QuizRun, Attempt; published revisions are immutable

## Context and Problem Statement

Quizzes are edited while competitions run and history must stay evaluable and auditable.

## Decision Drivers

* History never rewritten
* Running attempts unaffected by edits
* Clear competition boundaries

## Considered Options

* Distinct Quiz / QuizRevision / QuizRun / Attempt / Participant / Scoreboard concepts
* Single mutable quiz with result table
* Versioned quiz rows without runs

## Decision Outcome

Chosen option: "Distinct Quiz / QuizRevision / QuizRun / Attempt / Participant / Scoreboard concepts", because it isolates content versions from competition runs and individual attempts.

### Consequences

* Good, because attempt pinned to one revision at start; edit = new revision
* Good, because scoreboard is only a projection
* Bad, because more entities and joins
* Bad, because revision snapshots duplicate content

### Confirmation

[AC-04](../acceptance-criteria.md).

## More Information

FR-08, FR-09, FR-19; [../modules/domain.md](../modules/domain.md). The bank question pool is copied into the revision at publication.

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)

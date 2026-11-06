---
status: accepted
date: 2026-11-05
---

# ADR-0035: Immediate solutions only without competition; "no going back" enforced by the page

## Context and Problem Statement

Answers are normally submitted together at the end. Two options need a decision about who enforces them:

* "One by one without going back" (FR-17): bypassing it gives a small advantage.
* "Reveal the solution after each question" (FR-23): without locking the answer first, a participant
  can read all solutions and then submit full marks.

Typical use of immediate solutions is learning (training, museums, practice), where cheating harms
nobody.

## Decision Drivers

* Trustworthy scoreboards and draws
* Few writes to SQLite, which has a single writer
* Proportionate effort

## Considered Options

* Immediate solutions only in runs without scoreboard and rewards; no answer locking
* Immediate solutions everywhere, with server-side answer locking
* Server-side locking after every question in both modes

## Decision Outcome

Chosen option: "Immediate solutions only in runs without scoreboard and rewards; no answer locking",
because it prevents the serious fraud without per-question writes.

Rules:

* Immediate solutions can be enabled only if the run has a hidden scoreboard and no rewards. Conflicting
  settings are blocked through module requirements ([ADR-0034](0034-module-requirements-on-settings.md)).
* The server returns a solution only on request for a question in such a run, and stores nothing for it.
* "No going back" is enforced only by the page. It is a user-interface rule, not a security boundary.

### Consequences

* Good, because no locking, no extra writes and one submission flow
* Good, because learning quizzes also work without storing results
* Bad, because a competition with immediate solutions is not possible in v1.0
* Bad, because "no going back" can be bypassed by editing the page

### Confirmation

[AC-18](../acceptance-criteria.md).

## More Information

Resolves [OQ-12](../open-questions.md). Answer locking may be added later as an extension.

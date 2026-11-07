---
status: accepted
date: 2026-11-06
---

# ADR-0038: Policy for a new revision during an open round; settings with quiz override

## Context and Problem Statement

The architecture says a run can use several revisions ([ADR-0008](0008-scoreboard-revision-modes-default-separate.md)),
but stage A kept a run on the revision it was opened with, so a correction reached players only after closing
the round. A typo fix and a change to a live competition need different behaviour, and operators differ in what
they want. The project also had no place for application settings.

## Decision Drivers

* A correction can reach players while the round runs
* A participant does not lose answers to questions that did not change
* Published revisions and pinned attempts stay intact (AC-04)
* The admin decides, once or per quiz, without code

## Considered Options

* A policy with a global default and a per-quiz override
* Always ask at publication
* One fixed behaviour

## Decision Outcome

Chosen option: "A policy with a global default and a per-quiz override", because it lets operators decide once
while `ask`, the default, keeps the decision with the admin.

Rules:

* `revision_switch_policy` has the values `ask`, `notify_switch` and `let_finish`. See `FR-47` in
  [domain.md](../modules/domain.md).
* `stay` exists only as a choice at publication. It writes no revision history row and changes no earlier decision.
* The latest stored decision applies to all older attempts of the round.
* The notice and the "Switch" button are a page rule, not a security boundary, as in
  [ADR-0035](0035-immediate-solutions-only-without-competition.md). A modified client can still submit an attempt
  that was not switched, and the server evaluates it against its own revision.
* A switched attempt cannot be submitted, so one start gives one result. The new attempt keeps the original start
  time, so switching buys no time.
* Settings live in `app_setting` with a code catalogue of keys, values and defaults. Module configuration stays
  in `plugin_configuration` (D4).

### Consequences

* Good, because a correction reaches players at once, and they keep their unchanged answers
* Good, because later milestones can add settings without new tables
* Bad, because a correction to one option's text empties that question's answer, since any definition change counts
* Bad, because participants poll every 30 seconds, which adds some read load
* Bad, because a participant without JavaScript gets no notice and finishes on the old revision
* Bad, because with the default scoreboard mode in Stage C even a typo fix splits the scoreboard until the admin merges it

### Confirmation

Service and API tests for each policy, and `tests/integration/test_revision_switch.py` for the whole flow over HTTP.
[AC-19](../acceptance-criteria.md), [AC-20](../acceptance-criteria.md).

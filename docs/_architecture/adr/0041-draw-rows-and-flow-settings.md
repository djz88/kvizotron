---
status: accepted
date: 2026-11-07
---

# ADR-0041: Draw rows set points; flow settings apply immediately and freeze on the attempt

## Context and Problem Statement

Milestone B3 brings question banks, random selection, navigation modes and revealing answers. Three things needed a decision: how drawn questions are worth points when participants get different ones, whether navigation and reveal are part of a revision, and how a participant reaches answers after a run closes, given that a result has no lasting address and answers are not stored.

## Decision Drivers

* Everyone in a run plays for the same maximum, because Stage C compares them on a scoreboard
* A published revision never changes; a bank edit does not reach it
* Few writes and no stored answers
* Simple settings that work like the existing ones

## Considered Options

* Points on the draw row, or points carried by each bank question
* Flow settings in the revision, or in the settings catalogue with a quiz override
* "After the run closes" in B3 with a lasting link, or moved to Stage C

## Decision Outcome

* **The draw row sets the points.** `max_score` is own points plus count × points per row, so it does not depend on the draw. The scoring strategy stays on the question.
* **Flow settings live in the settings catalogue**, global with a quiz override, effective for new attempts at once and creating no draft. An attempt freezes them at start in `settings_json`, next to the questions it got in `selection_json`. A conflict the form cannot see, from a later global change, falls back to `at_end` with a warning on the quiz.
* **Showing answers after the run closes moves to Stage C**, with identity and a lasting result page. In B3 the list exists only in the response to the submission, so nothing about answers is stored.

Publication copies each row's usable questions into the revision. A bank question whose pool differs from that copy counts as an unpublished change.

### Consequences

* Good, because maxima are equal and a scoreboard stays fair
* Good, because a settings change cannot alter an attempt in progress, and it needs no new revision
* Bad, because flow settings are not in the revision history, only in the audit log
* Bad, because a participant who leaves the result page cannot see the answers again until Stage C

### Confirmation

`tests/domain/test_draws.py`, `tests/domain/test_flow_settings.py`, `tests/integration/test_banks_and_flow.py`.

## More Information

FR-17, FR-18, FR-19, FR-23; [ADR-0035](0035-immediate-solutions-only-without-competition.md), [ADR-0038](0038-revision-switch-policy-and-settings.md).

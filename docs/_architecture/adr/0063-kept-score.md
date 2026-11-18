---
status: accepted
date: 2026-11-12
---

# ADR-0063: Kept score: last and average

## Context and Problem Statement

The run setting `official_attempt` chose one attempt per participant, the first or the best ([ADR-0026](0026-scoreboard-tie-break-rule.md), [ADR-0051](0051-scoreboard-participants-and-official-attempt.md)). Test-like quizzes need two more rules: the last attempt counts, or the mean of all of them. A mean is not an attempt, yet rewards, draws, the scoreboard and the export all read "the official attempt".

## Decision Drivers

* Every consumer reads the same figures; none computes its own mean
* An entitlement ([ADR-0053](0053-rewards-tiers-alternates-and-draw-history.md)) still points at a real attempt
* First and best behave exactly as before
* Existing quizzes do not change: attempts waiting for grading count for nothing, as before

## Considered Options

* A `Kept` value from the domain (attempt, figures, count, rule, waiting) that every consumer uses
* Each consumer computes the mean itself
* Store a synthetic attempt

## Decision Outcome

Chosen option: "A `Kept` value from the domain", because the figures are computed once and a stored synthetic attempt would invent data.

* **Rules.** `last` is the attempt with the latest `submitted_at` (equal times: the greater attempt id). `average` is a new `ScoreEntry` from `pick_official`: score and maximum are the means of the submitted attempts, the other fields are those of the last one. An unknown rule raises `ValueError` instead of falling back to best.
* **Figures.** Under average `correct` is the floor of the mean and `questions` the mean rounded half up; the representative attempt is the last submitted one.
* **`results.kept(participant)`** returns `Kept` or None (no submitted, scored attempt). `official_attempt` is `kept(...).attempt`. Attempts waiting for grading are ignored by every rule, as before: rewards, draws, the scoreboard, the export and `official_attempt` count only submitted, scored attempts.
* **Waiting.** `Kept.waiting` is a flag: under `first` the earliest finished attempt is pending, under `last` the latest, under `best` and `average` any. Only the pass mark uses it (no verdict while waiting).
* **Entitlements** of an average point at the last attempt. The attempts export marks every submitted attempt the run's revision mode counts as official under average, otherwise the chosen one.

### Consequences

* Good, because rewards, draws, the export and the pass mark read one computed value
* Bad, because under `separate` the board ranks one row per revision table while `kept` is one attempt over all revisions, and under `average` the board ranks by the mean of percents while `kept` keeps the mean of points over the mean of maxima; which attempts `kept` counts follows the board's revision mode (addendum of 2026-11-17 to [ADR-0053](0053-rewards-tiers-alternates-and-draw-history.md), [TD-047](../TECH_DEBT_archive.md))

### Confirmation

`tests/contracts/result_view.py`, `tests/domain/test_results_board.py`, `test_entitlements.py`, `test_prize_draws.py` and `test_results_export.py`.

## More Information

Design: `docs/superpowers/specs/2026-11-12-test-add-ons-design.md`.

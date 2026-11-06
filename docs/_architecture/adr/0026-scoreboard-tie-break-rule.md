---
status: accepted
date: 2026-11-05
---

# ADR-0026: Scoreboard and best-attempt tie-break rule

## Context and Problem Statement

FR-27 requires an explicit rule for an equal best score and a deterministic recalculation. FR-29 lets
the admin choose primary and secondary sorting, but participants can still be tied after it. Different
events want different outcomes: some accept a shared place, others need a unique ranking.

## Decision Drivers

* Admin control per run
* Determinism across recalculations
* Unique ranking available when an event needs it

## Considered Options

* Admin chooses per run: shared place, earlier submission, or random order
* One fixed rule with a unique ranking: score, duration, submission time, ID
* One fixed rule: shared place

## Decision Outcome

Chosen option: "Admin chooses per run: shared place, earlier submission, or random order", because the
right outcome depends on the event, and the last two preserve a unique ranking.

After the admin's primary and secondary sorting, remaining ties follow `tie_break_policy`:

| Policy | Behaviour | Ranks |
|---|---|---|
| `SHARED_RANK` (default) | Tied participants share a place; rows displayed by submission time | 1, 1, 3 |
| `EARLIER_SUBMISSION` | Earlier `submitted_at` ranks higher; identical timestamps fall back to attempt ID | unique |
| `RANDOM` | Order given by a hash of a per-run random value and the participant ID | unique |

Rules:

* `RANDOM` uses a value from a CSPRNG stored once with the run, so the order stays the same in every
  recalculation. It only orders the scoreboard and is not a prize draw (FR-37).
* Between equal-scoring attempts of **one participant**, the earlier attempt counts. This is fixed,
  not an admin choice.

### Consequences

* Good, because each event gets the outcome it needs
* Good, because every policy is deterministic
* Bad, because it adds one setting and three behaviours to test
* Bad, because `EARLIER_SUBMISSION` favours early players in runs open for a long time
* Bad, because `RANDOM` is auditable only at application level, like the draw ([ADR-0013](0013-manual-draw-csprng-append-only-audit.md))

### Confirmation

Unit tests of the ranking projection: each policy gives the same order in repeated recalculations.

## More Information

Resolves [OQ-05](../open-questions.md). The default policy and the one-participant rule are documentation proposals to be confirmed in review.

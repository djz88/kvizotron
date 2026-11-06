# Plugin: scoring strategies

| | |
|---|---|
| Contract | `ScoringStrategyPlugin` |
| Package | `app/plugins/scoring/` |
| Stage | A (basic), B (partial and others) |

## Requirements

- `FR-24` Each question type supplies its supported scoring strategies (e.g. all-or-nothing, partial
  points) through a unified contract; admin chooses a strategy per question/quiz within compatibility.
- `FR-25` A result contains `earned_points`, `max_points`, `percentage`, `correct_count` (only where
  meaningfully defined), optionally `duration_ms`. Percentages are computed from exact values and
  rounded **only for display**, never for threshold evaluation.
- `FR-26` Reward thresholds are **either percentage or absolute number of correct questions/points**;
  they are not equivalent. Example: 4 of 5 = 80 %, not 90 %.

## Behaviour

- `evaluate()` is pure and server-side, over immutable definition + supplied answer
  ([contracts](../modules/contracts.md) invariant 2). Client scores are never trusted.
- Strategy settings that affect evaluation are snapshotted into the revision/run.
- Mixed scoring ([ADR-0033](../adr/0033-image-answer-question-type.md)): `evaluate()` returns only the
  automatic points; `max_points` also includes the manual part. Manual points are stored separately
  and only an authenticated admin can set them.

## Acceptance

[AC-10](../acceptance-criteria.md): five equally weighted questions, 4 correct = 80 %; 90 % threshold reward is not granted.

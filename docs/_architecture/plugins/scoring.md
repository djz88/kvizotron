# Plugin: scoring strategies

| | |
|---|---|
| Contract | `ScoringStrategyPlugin` |
| Package | `app/plugins/scoring/` |
| Stage | A (all or nothing), B2 (partial) |

## Requirements

- `FR-24` Each question type supplies its supported scoring strategies (e.g. all-or-nothing, partial
  points) through a unified contract; admin chooses a strategy per question/quiz within compatibility.
- `FR-25` A result contains `earned_points`, `max_points`, `percentage`, `correct_count` (only where
  meaningfully defined), optionally `duration_ms`. Percentages are computed from exact values and
  rounded **only for display**, never for threshold evaluation.
- `FR-26` Reward thresholds are **either percentage or absolute number of correct questions/points**;
  they are not equivalent. Example: 4 of 5 = 80 %, not 90 %.

## Behaviour

- The question type grades the answer against the immutable definition, and `evaluate(grade, settings)` only weighs the grade ([ADR-0040](../adr/0040-question-types-grade-and-strategies-weigh.md)). Both are pure and server-side ([contracts](../modules/contracts.md) invariant 2). Client scores are never trusted.
- `all_or_nothing` pays the points when `right == total` and `wrong == 0`.
- `partial` pays `points * max(0, right - wrong) / total`, computed once with `Fraction` and rounded to 4 places at the end. Ticking everything does not pay. Trick and yes/no questions have `total = 1`, so they behave as all or nothing.
- Points are whole numbers from 1 to 100 per question, default 1.
- Strategy settings that affect evaluation are snapshotted into the revision/run.
- Mixed scoring ([ADR-0033](../adr/0033-image-answer-question-type.md)): `evaluate()` returns only the
  automatic points; `max_points` also includes the manual part. Manual points are stored separately
  and only an authenticated admin can set them. The image answer carries its automatic share through
  `ItemGrade`, so `partial` pays it ([ADR-0047](../adr/0047-image-answer-photo-visibility.md)).

## Acceptance

[AC-10](../acceptance-criteria.md): five equally weighted questions, 4 correct = 80 %; 90 % threshold reward is not granted.

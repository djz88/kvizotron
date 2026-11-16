# Plugin: rewards (rewards.threshold)

| | |
|---|---|
| Contract | `RewardPlugin` |
| Package | `app/plugins/rewards/` |
| Stage | C |
| Decision | [ADR-0053](../adr/0053-rewards-tiers-alternates-and-draw-history.md) |

## Requirements

- `FR-36` Reward modes: none; one or more performance thresholds; direct entitlement; draw among all;
  draw among eligible (e.g. minimum score). Admin defines reward name/description, rules and
  claim instructions. The system stores the entitlement and its fulfilment status; it does **not**
  issue voucher codes (voucher codes: LATER).

## Behaviour

- Rule kinds: `threshold` (unit `percent`, `points` or `correct`, a value), `participation`, `manual`
  and `draw` (executed by [drawings.md](drawings.md)). The direct entitlement of FR-36 is both
  participation and manual. Texts (name, description, claim instructions) per quiz language, each
  falling back to the quiz's default language.
- Threshold unit is explicit: percentage **or** absolute correct count/points (FR-26, [scoring.md](scoring.md)).
- Thresholds evaluated on exact values, never on rounded display values: reached means `>=` against
  the attempt's own maximum, manual points included, and for `correct` the attempt's own number of questions.
- Entitlements created in the same transaction as the submission result. With pending manual grading
  they are evaluated once nothing is pending ([ADR-0033](../adr/0033-image-answer-question-type.md)).
- Draw-based rewards are executed by [drawings.md](drawings.md); both use the same eligibility policy
  ([contracts](../modules/contracts.md) invariant 5).
- The participant sees their own entitlements (granted or handed over) with name, description and
  claim instructions on the result page and the private result link `/v/{token}`, a draw win after the
  draw. The quiz page names the run's rewards by name and description, without thresholds. Nothing is
  shown before submission, and nothing without rules.
- Where rules come from, tiers, the contact setting, recomputation and who may cancel:
  [ADR-0053](../adr/0053-rewards-tiers-alternates-and-draw-history.md).

## Settings

Declared by the module (group `rewards`, level `advanced`, scopes global and quiz: they apply to the
whole run, not to one question):

| Key | Values | Default | On the run |
|---|---|---|---|
| `reward_source` | `none`, `previous_run`, `quiz` | `none` | no: it only fills a new run with rules |
| `reward_thresholds` | `highest`, `all` | `highest` | `QuizRun.rewards_json`, fixed once the run opens |
| `winner_contact` | `warn`, `require_email`, `silent` | `warn` | `QuizRun.rewards_json`, fixed once the run opens |

## Contract

`RewardPlugin` (port `reward`, implementation `rewards.threshold`) is pure: `share(rule, figures)` gives
the threshold as a share of the attempt, `reached(rule, figures)` compares, and
`qualifies(rules, figures, mode)` returns the ids of the reached threshold rules, under `highest` only
the largest share with ties by rule order. Rules, entitlements, copies and transactions live in
`app/domain/rewards.py`.

## Known limit

The official attempt for rewards (and for a draw) is chosen over all of the participant's submitted
attempts in the run, whatever the scoreboard's revision mode. Under `separate` or `latest` the
scoreboard may count a different attempt than the one that earned the reward.

## Data owned

`reward_rule`, `reward_entitlement` ([../data-model.md](../data-model.md)); the settings in
`quiz_run.rewards_json`.

The module cannot be disabled while a planned, open or closed run has a threshold rule or a draw rule with
a minimum ([ADR-0053](../adr/0053-rewards-tiers-alternates-and-draw-history.md)); the submit transaction calls it.

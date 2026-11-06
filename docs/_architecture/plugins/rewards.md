# Plugin: rewards (threshold-rewards)

| | |
|---|---|
| Contract | `RewardPlugin` |
| Package | `app/plugins/rewards/` |
| Stage | C |

## Requirements

- `FR-36` Reward modes: none; one or more performance thresholds; direct entitlement; draw among all;
  draw among eligible (e.g. minimum score). Admin defines reward name/description, rules and
  claim instructions. The system stores the entitlement and its fulfilment status; it does **not**
  issue voucher codes (voucher codes: LATER).

## Behaviour

- Threshold unit is explicit: percentage **or** absolute correct count/points (FR-26, [scoring.md](scoring.md)).
- Thresholds evaluated on exact values, never on rounded display values.
- Entitlements created in the same transaction as the submission result. With pending manual grading
  they are evaluated once nothing is pending ([ADR-0033](../adr/0033-image-answer-question-type.md)).
- Draw-based rewards are executed by [drawing.md](drawing.md); both use the same eligibility policy
  ([contracts](../modules/contracts.md) invariant 5).

## Data owned

`reward_rule`, `reward_entitlement` ([../data-model.md](../data-model.md)).

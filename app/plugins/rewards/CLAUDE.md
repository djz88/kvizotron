# Module: app/plugins/rewards

Plugin `rewards.threshold`, port `reward`: pure rules for threshold rewards. The share of the threshold from an attempt (`share`), whether an attempt reached the threshold (`reached`, `>=` on exact `Decimal`s) and which thresholds a participant gets according to the `reward_thresholds` setting (`qualifies`: `highest` only the largest share, a tie decided by the order of the rules; `all` all reached ones).

## What the module contains

`thresholds.py` (`ThresholdReward`), `manifest.py` with three reward settings (`reward_source`, `reward_thresholds`, `winner_contact`; scope global and quiz, they apply to the whole run), `apps.py`.

## What the module is not

It touches neither the database nor the request. Rules, claims, copies onto a run and transactions are handled by the domain; the plugin receives `ThresholdRule` and `AttemptFigures` and returns rule ids. Drawing is in `app/plugins/drawings/`.

## Forbidden

Importing from `app/domain`, `app/api` or from another plugin: only `app.contracts` is allowed. Comparing rounded numbers or `float`.

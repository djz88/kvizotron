# Module: app/plugins/results

Plugin `results.local`, port `result_view`: pure result rules. Which of a participant's attempts counts (`pick_official`), the scoreboard order and ties (`rank`, ADR-0026) and a score summary for statistics (`summarize`). It judges neither the pass mark nor the reveal of answers: the domain does that from the values on the run.

## What the module contains

`ranking.py` (`LocalResultView`), `manifest.py` with thirteen settings: twelve for the scoreboard and `pass_mark` (scope global and quiz, they apply to the whole run; `official_attempt` also has `last` and `average`, ADR-0063), `apps.py`.

## What the module is not

It touches neither the database nor the request. Attempts, visibility, names and the cache are handled by `app/domain/results.py` and `app/domain/run_stats.py`; the plugin receives `ScoreEntry` and returns the order.

## Forbidden

Importing from `app/domain`, `app/api` or from another plugin: only `app.contracts` is allowed. Randomness for ties only from the value stored on the run (`seed`), never `random`.

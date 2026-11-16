# Plugin: results & scoreboard (results.local)

| | |
|---|---|
| Contract | `ResultViewPlugin` (port `result_view`) |
| Package | `app/plugins/results/` |
| Stage | C |
| Decision | [ADR-0008](../adr/0008-scoreboard-revision-modes-default-separate.md), [ADR-0012](../adr/0012-configurable-retention-profiles-and-stateless-mode.md) |

Storing attempts and results belongs to the [domain](../modules/domain.md); this plugin provides the
views over them ([ADR-0037](../adr/0037-providers-and-plugins.md)). Further views and dashboards are
additional `ResultViewPlugin` modules.

## Requirements

- `FR-29` Admin controls scoreboard visibility (hidden, immediately, after close), columns (e.g.
  nickname, score, rank, time), primary and secondary sorting. E-mail and internal identifiers are
  never exposed on the public scoreboard.
- `FR-30` The scoreboard is bound to a `QuizRun`. By default the attempts of all revisions share one
  table ranked by percent of each attempt's own revision maximum; the admin can switch a run to one
  table per revision or only the latest revision. Several runs of a quiz can show one shared board on
  a main run without moving data. A restarted run always starts without previous results.
- `FR-31` In the no-retention mode the score is computed and shown to the participant without
  persistence. Scoreboard, subsequent draw, attempt history and export of stored results are not
  available in this mode; the admin UI shows these dependencies before activation.
- `FR-43` Admin statistics: participants, numbers of attempts and completions, average and
  distribution of scores, per-question success rate, results by run and revision. Test data are kept
  separate.

## Behaviour

- Scoreboard is a projection, not a source of truth: settings in `quiz_run.results_json`, the board computed from attempts by `app/domain/results.py` with this module's `pick_official` (also `last` and `average`), `rank` and `summarize` ([ADR-0051](../adr/0051-scoreboard-participants-and-official-attempt.md)).
- One row per browser: a visible board sets the participant cookie whatever the repeat rule. Live names can be anonymised with the quiz's anonymous label.
- Ties remaining after the admin's sorting follow the run's `tie_break_policy`: shared place, earlier
  submission or random order ([ADR-0026](../adr/0026-scoreboard-tie-break-rule.md)).
- `revision_mode` (global and quiz, copied to the run and switchable on the run page): `percent` (default) ranks all revisions in one table by percent of each attempt's own revision maximum, `separate` gives one table per revision, `latest` only the current revision ([ADR-0065](../adr/0065-scoreboard-by-percent-and-shared-boards.md), [AC-06](../acceptance-criteria.md)). Runs linked to a main run share its public board, ranked by percent, without moving data ([AC-177](../acceptance-criteria.md)).
- With pending manual grading the public scoreboard stays hidden while anything is pending ([ADR-0033](../adr/0033-image-answer-question-type.md)). This limits FR-29 through the
  module's requirements (FR-46).
- The kept score (`results.kept`, [ADR-0063](../adr/0063-kept-score.md)) follows `official_attempt`: first, best, last or average ([AC-174](../acceptance-criteria.md)). The module also declares `pass_mark` (0 to 100 percent of the maximum, global and quiz, copied to `results_json`, [AC-172](../acceptance-criteria.md)); an attempt passes on its own percentage, a participant on the kept score, and the public scoreboard shows a tick only.
- `scoreboard_runs` (global and quiz, read live, not copied to a run): "current" (default) offers only the shown run's board on the quiz page, "all" adds the boards of the other normal runs that are public now (`results.public_runs`, one query), newest first; each run keeps its own visibility and its own address works either way ([AC-176](../acceptance-criteria.md)).
- Test attempts excluded from all public projections and real statistics.
- Public links to archived results are off by default, with a per-run switch ([ADR-0031](../adr/0031-public-links-to-archived-results.md)).

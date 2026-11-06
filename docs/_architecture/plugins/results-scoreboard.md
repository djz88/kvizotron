# Plugin: results & scoreboard (local-results)

| | |
|---|---|
| Contract | `ResultViewPlugin` |
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
- `FR-30` The scoreboard is bound to a `QuizRun`. Admin decides whether revisions are separated,
  merged only if compatible, or only the latest shown. A restarted run always starts without previous
  results.
- `FR-31` In the no-retention mode the score is computed and shown to the participant without
  persistence. Scoreboard, subsequent draw, attempt history and export of stored results are not
  available in this mode; the admin UI shows these dependencies before activation.
- `FR-43` Admin statistics: participants, numbers of attempts and completions, average and
  distribution of scores, per-question success rate, results by run and revision. Test data are kept
  separate.

## Behaviour

- Scoreboard is a projection (`scoreboard_policy`), not a source of truth.
- Ties remaining after the admin's sorting follow the run's `tie_break_policy`: shared place, earlier
  submission or random order ([ADR-0026](../adr/0026-scoreboard-tie-break-rule.md)).
- `MERGE_COMPATIBLE` is refused when max points differ ([AC-06](../acceptance-criteria.md)).
- With pending manual grading the public scoreboard stays hidden until the run is closed and nothing
  is pending ([ADR-0033](../adr/0033-image-answer-question-type.md)). This limits FR-29 through the
  module's requirements (FR-46).
- Test attempts excluded from all public projections and real statistics.
- Public links to archived results are off by default, with a per-run switch ([ADR-0031](../adr/0031-public-links-to-archived-results.md)).

# Combined scoreboards — design

Date: 2026-11-16. Decided with the user in chat; this document records those decisions.

## Intent

An admin wants to see everyone in one table without clicking through revisions or runs:

1. Inside one run, attempts on different revisions share one table by default.
2. Several runs of one quiz can show one shared scoreboard, without moving any data.
3. A full merge of runs (moving attempts and participants) is out of scope; it is only recorded.

## Decisions taken by the user

- The scoreboard revision mode gets a new value **one table by percent** and it becomes the default,
  globally and per quiz (setting `scoreboard_revision_mode`, inherited global → quiz as today).
- **Separate per revision** and **only the latest revision** stay as they are.
- A 1:1 merge by points is not offered.
- Existing runs switch too: every non-test run with `separate`, or with the old per-run merge
  switched on, becomes `percent`. `latest` stays.
- Several runs can show one shared board: on the quiz's Runs page the admin ticks runs and picks the
  main run. Only display; data, rules, rewards and draws stay with each run.
- A full merge of runs is only mentioned (TECH_DEBT), not designed.

## Behaviour

### One table by percent (inside one run)

- Rows from all revisions of the run are ranked together by the percentage of the maximum of the
  revision the attempt was played on. Ties then follow the run's existing second sort and tie policy
  (ADR-0026).
- Each row still shows its own score and its own maximum (`7 / 10`, `8 / 12`); the percent column
  is the ranked value. The pass mark is judged per row against its own maximum (as today).
- The equal-maximum restriction of ADR-0008 and AC-06 no longer applies: percent makes different
  maxima comparable.
- The per-run "merge revisions" page and its confirmation are removed. The revision mode joins the
  run's display settings (`RESULT_DISPLAY_KEYS`) so the admin can switch a single run between the
  three modes on the run page, also after the run ended. It only changes what is shown: rewards and
  draws do not read it (TD-047).
- `place_of` (own place on the result page) uses the same table.

### Shared board of several runs

- On the Runs tab of a quiz the runs table gets a checkbox per run and a choice of the main run.
  Saving links the ticked runs to the main run; a separate button splits a shared board again.
- Rules: same quiz; test runs are never included; a run belongs to at most one shared board; the
  main run cannot itself be a member of another; at least two runs. Archived quizzes are read-only
  (`authoring.ensure_editable`). Each change is audited (`run.board_combined`, `run.board_split`).
- The main run's public scoreboard (and projector) shows one table: the candidates of every linked
  run, each run filtered by its own revision mode (`latest` keeps only that run's current revision),
  each participant's counted attempt chosen by that run's own official-attempt rule, then all ranked
  together by percent with the main run's tie rules. Visibility, columns, live names and unnamed rows
  follow the main run's settings.
- A participant is per run, so the same browser in two runs gives two rows. Anonymous labels carry
  the run number when the board is shared ("Run 2 · Player 3").
- Grading pending in any linked run holds the shared board like it holds a run's own board.
- Member runs keep their own scoreboard pages unchanged. The main run page and the shared public
  board say which runs are combined.
- The public board cache of the main run is dropped whenever a member's board is dropped.
- A participant's own place on the result page stays the place in their own run.

### Full merge of runs (only recorded)

A TECH_DEBT entry lists what a full merge would have to decide: whose run rules win (data profile,
retention, participant rules, access code, rewards, schedule), duplicate browsers and nicknames,
immutable entitlements and draw history, what happens to the source run, its exports and private
result links. It needs its own ADR replacing ADR-0007 before any work.

## Constraints

- Project rules in `CLAUDE.md`: QuizRun is "běh" in Czech UI, never "kolo"; the server computes all
  scores; published revisions are immutable; a restart never takes over results (still true: the
  shared board copies nothing).
- Settings change follows the `kvizotron-add-setting` skill; the new value needs cs and uk texts.
- `app/domain/models.py` and migrations are VELKÁ-tier changes.

## Documentation

- New ADR superseding ADR-0008 (status accepted, the user decided).
- `FR-30` in `docs/_architecture/plugins/results.md`, `AC-06` in `acceptance-criteria.md`, one new
  AC for the shared board, `data-model.md`, `docs/configuration.md` if it lists the setting values.

## Left to the builder

Names of functions and templates, the exact Czech and Ukrainian wording, and the layout of the
checkbox column on the Runs page.

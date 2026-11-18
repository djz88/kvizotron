---
status: accepted
date: 2026-11-16
---

# ADR-0065: One scoreboard by percent across revisions by default, and a shared board of several runs

## Context and Problem Statement

[ADR-0008](0008-scoreboard-revision-modes-default-separate.md) shows one table per revision by default and lets the admin merge revisions only when their maximum points are equal, through a separate audited "merge revisions" page on the run. A run that switched to a revision with another maximum therefore splits its participants into several tables, and an admin who runs the same quiz in several runs (classes, evenings) has no way to show everyone in one table. The admin wants to see everyone in one table without clicking through revisions or runs, without moving any data.

## Decision Drivers

* An admin sees everyone in one table without clicking through revisions or runs
* Scores from revisions with different maxima stay comparable
* No attempt, participant, reward or draw moves between runs; a restart still never takes over results ([ADR-0007](0007-restart-creates-new-run-keeps-history.md))
* The revision mode moves no data; since the addendum of 2026-11-17 to [ADR-0053](0053-rewards-tiers-alternates-and-draw-history.md), rewards, draws and the pass mark count the attempt the board counts under it ([TD-047](../TECH_DEBT_archive.md))
* Fewer admin pages: no separate merge page with a confirmation

## Considered Options

* (a) Merge by points with equal maxima: the rule of ADR-0008, kept as it is
* (b) Merge by percent: rank the attempts of all revisions together by the share of the maximum of each attempt's own revision, as a new default revision mode
* (c) Merge 1:1 by points, whatever the maxima
* (d) Full merge of runs: move the attempts and participants of several runs into one run

## Decision Outcome

Chosen option: (b), together with a display-only shared board of several runs, because percent makes different maxima comparable without the admin judging revisions, and a shared board shows several runs in one table without touching their data. (a) leaves runs with changed maxima split; (c) was rejected by the user, since points out of different maxima are not comparable; (d) is deferred (TD-103).

### One table by percent inside one run

* `scoreboard_revision_mode` (inherited global → quiz) gets the value `percent`, "one table by percent", which becomes the default globally and per quiz. `separate` (one table per revision) and `latest` (only the run's current revision) stay unchanged.
* Rows from all revisions of the run are ranked together by the percentage of the maximum of the revision the attempt was played on. Ties then follow the run's second sort and tie policy ([ADR-0026](0026-scoreboard-tie-break-rule.md)).
* Each row still shows its own score and its own maximum (`7 / 10`, `8 / 12`); the percent column is the ranked value. The pass mark is judged per row against its own maximum ([ADR-0063](0063-kept-score.md)).
* The equal-maximum restriction of ADR-0008 no longer applies.
* The per-run "merge revisions" page, its confirmation and `results_json["merged"]` are removed. The revision mode joins the run's display settings (`RESULT_DISPLAY_KEYS`), so the admin switches a single run between the three modes on the run page, also after the run ended. A participant's own place on the result page uses the same table.
* Existing runs switch too: every non-test run with `separate`, or with the old merge switched on, becomes `percent`; `latest` stays.

### Shared board of several runs

* On the quiz's Runs page the admin ticks runs and picks the main run; saving links the ticked runs to the main run (`QuizRun.board_main`), a separate button splits the shared board again.
* Rules: same quiz; test runs never take part; a run belongs to at most one shared board; the main run cannot itself be a member of another; at least two runs. An archived quiz is read-only. Each change is audited (`run.board_combined`, `run.board_split`).
* The main run's public scoreboard and projector show one table: the candidates of every linked run, each run filtered by its own revision mode, each participant's counted attempt chosen by that run's own official-attempt rule, then all ranked together by percent with the main run's tie rules. Visibility, columns, live names and unnamed rows follow the main run's settings.
* A participant belongs to one run, so the same browser in two runs gives two rows; anonymous labels carry the run number when the board is shared, and on the admin's board every row does. Grading pending in any linked run holds the shared board and keeps its link off the quiz page. An archived member run's rows show publicly only when its archived results are public (a member with deleted data adds none); the link stays and the admin board shows them. The main run's board cache is dropped whenever a member's is.
* Only the display is shared: data, rules, rewards and draws stay with each run, member runs keep their own boards, and a participant's own place on the result page stays the place in their own run, and on a shared board the page says which run it counts. The projector shows each row's score of its own maximum and the percent, since rows are ranked by percent.

### Consequences

* Good, because a run with revisions of different maxima shows one table by default, and several runs can show one table, without moving data
* Good, because one admin page and one audited action less: the revision mode is a plain run display setting
* Good, because the shared board copies nothing: rewards and draws stay with each run and count the attempt that run's own board counts (addendum of 2026-11-17 to [ADR-0053](0053-rewards-tiers-alternates-and-draw-history.md), [TD-047](../TECH_DEBT_archive.md))
* Bad, because a percentage hides that revisions may differ in difficulty; the admin can still switch a run to one table per revision
* Bad, because existing runs change what they show after the upgrade (`separate` and merged runs become `percent`)
* Neutral, because [AC-06](../acceptance-criteria.md) changes meaning: it no longer tests the equal-maximum merge but the percent default and the switch on the run

### Confirmation

[AC-06](../acceptance-criteria.md) and [AC-177](../acceptance-criteria.md), with tests of the percent ranking, the data migration of existing runs, the run display switch, the shared board rules and the shared public board.

## More Information

Supersedes [ADR-0008](0008-scoreboard-revision-modes-default-separate.md). FR-30; [../modules/domain.md](../modules/domain.md), [../plugins/results.md](../plugins/results.md); official attempt and live names [ADR-0051](0051-scoreboard-participants-and-official-attempt.md); full merge of runs TD-103. Design: `docs/superpowers/specs/2026-11-16-combined-scoreboards-design.md`.

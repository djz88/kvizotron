---
status: proposed
date: 2026-11-16
---

# ADR-0064: A run copies its flow, sources and answers visibility when planned or opened

> The flow and sources part was decided on 2026-11-18 by [ADR-0069](0069-run-keeps-flow-settings.md). This ADR stays `proposed` for answers visibility.

## Context and Problem Statement

A run copies most of its behaviour from the settings when it is planned or opened: the time limit (`attempt_limit_sec`, [ADR-0048](0048-run-timing.md)), the participant rules (`participant_rules_json`, [ADR-0049](0049-participants-and-access-code.md)), the data profile (`retention_json`, [ADR-0050](0050-data-profile-and-local-resume.md)), the scoreboard (`results_json`, [ADR-0051](0051-scoreboard-participants-and-official-attempt.md)) and the rewards (`rewards_json`, [ADR-0053](0053-rewards-tiers-alternates-and-draw-history.md)). Five values are still read live from the quiz ([ADR-0041](0041-draw-rows-and-flow-settings.md): "effective for new attempts at once"):

* navigation and page size, the reveal moment and level, and shuffling of questions and options: `settings.flow(run.quiz)` in `app/domain/attempts.py` at each attempt start, frozen only on the attempt;
* sources on the result: `settings.resolve(SHOW_SOURCES, quiz, question)` in `result_sources` in `app/api/rendering.py`, at every rendering, also for finished attempts;
* the reveal clash with rewards: `rewards.conflicts` in `app/domain/rewards.py` checks the live `REVEAL_MOMENT`;
* answers visibility: `settings.answers_visibility(quiz)` and `settings.visibility_conflict(quiz)` judge the live visibility against the quiz's live data profile, not the run's copied one (TD-036); `visibility.participant_sees_answers` and `walkthrough.shows_answers` use them.

So a settings change, or a new quiz type ([ADR-0062](0062-quiz-type-port.md)), during an open run changes the run halfway: later participants get another navigation or reveal than earlier ones, and result pages of finished attempts gain or lose sources (TD-101). The quiz types overview only warns about it. The test add-ons ([ADR-0063](0063-kept-score.md), `docs/superpowers/specs/2026-11-12-test-add-ons-design.md`) kept the new "after the run closes" reveal live for the same reason: copying was left for later, not rejected.

## Decision Drivers

* A run behaves the same for every participant from opening to closing, as a competition and an exam expect
* An admin can predict what a settings change does: one rule for all run values, not two
* What a participant sees about answers is judged against what the run actually stores
* Little code and one migration; no new admin form for v1.0
* Test links keep following the quiz as it is now ([ADR-0044](0044-preview-and-test-links.md))

## Considered Options

* (a) Copy navigation, reveal, shuffle, sources and answers visibility onto the run when it is planned or opened, and read them from the run
* (b) Keep reading them live, and warn on the quiz-type bar and on the quiz settings page while a run is planned or open

## Decision Outcome

Proposed option: (a), because the time limit, participants, data profile, scoreboard and rewards already work this way, so the admin learns one rule ("a setting reaches the next run"), a running competition cannot change under its participants, and the copy also fixes TD-036, which (b) leaves open. The test add-ons spec kept reveal live only for lack of time, not by a decision against copying.

### Option (a) in detail

* **What is copied.** A new field `QuizRun.flow_json` (JSON, default `{}`) holds the values resolved global → quiz at that moment: `navigation`, `page_size`, `moment` (after the flow clash fallback of `settings.flow`), `level`, `shuffle_questions`, `shuffle_options`, `show_sources` and `answers_visibility`. Question-level values (`shuffle_options`, `show_sources` set on a question) still come from the question in the published revision, which is already frozen.
* **When.** In the same places that copy the other run values: `run_schedule.plan` and `run_schedule.update_plan` (planning and editing a plan) and `authoring.open_run` (opening at once, also behind `run_schedule.open_now`). A planned run that opens keeps what it got at planning, like the other values. No per-run form fields: the copied values are shown read-only in two places, on the plan page (what a planned run will use) and on the run page (what an open or closed run uses).
* **Where they are read.**
  * `attempts.start`: `settings.flow(run.quiz)` becomes a `flow_of_run(run)` that reads `flow_json`; the attempt still freezes them in `settings_json`, so a resumed attempt is unchanged.
  * `rendering.result_sources(questions, quiz, locale)` changes signature to take the run instead of the quiz, and reads the quiz-level `show_sources` from it; a question value still wins. Its callers change with it: `app/api/play.py` passes `attempt.run`, and `app/api/admin_preview.py`, which has no run, passes a value resolved from the quiz (the preview follows the quiz live).
  * `rewards.conflicts`: the reveal check reads the run's `moment`.
  * `settings.answers_visibility` and `settings.visibility_conflict` get a run variant that judges the run's copied visibility against the run's copied profile (`data_policy.of(run)`); `visibility.participant_sees_answers` and `walkthrough.shows_answers` use it. The quiz variant stays for the quiz pages, which speak about the next run: the `flow_conflict` and `visibility_conflict` warnings in `app/api/admin_quizzes.py` keep calling `settings.flow(quiz)` and `settings.visibility_conflict(quiz)`.
  * **Run clashes move from the settings forms to plan and open time.** `setting_rules.clashes` refuses a quiz or global value today when a planned or open run (`_live_runs`) would clash with it: `RUN_BOARD` (reveal after each question while a run shows a scoreboard), `RUN_REWARDS` (the same while a run has reward rules) and `RUN_PROFILE` (reveal after close while a run keeps no answers). Under (a) a quiz value no longer reaches a planned or open run, so these three clashes and `_live_runs` are removed from the quiz and global settings forms and from the quiz-type check; the quiz-level clashes (between values of the quiz itself) stay. The same conditions are checked once, when the run copies the values: `results.ensure_run_allowed` (scoreboard against the copied reveal moment, also in `results.set_display`) and `run_rewards.ensure_allowed` → `rewards.conflicts` (rewards against the copied reveal moment), and `data_policy.ensure_run_allowed` → `after_close_conflicts` (a profile that keeps no answers against reveal after close). These checks already run at planning and opening; under (a) they read the run's copy instead of `settings.resolve(REVEAL_MOMENT, quiz)`. A refused plan or opening shows the same message the settings form shows today.
  * Test runs (`run_links.create`) and the preview keep reading the quiz live; `flow_of_run` falls back to `settings.flow(run.quiz)` for a test run and for a run with an empty `flow_json`.
* **Migration.** A schema migration adds `flow_json`; a data migration fills it for every existing run (all statuses) with the values the quiz resolves at migration time, which are the values those runs show today. Attempts need nothing: they already froze their flow.
* **What changes for admins.** A settings change or a new quiz type no longer affects a planned or open run; the next planned or opened run picks it up. To apply a change to a running competition, the admin closes the run and opens a new one, as for the time limit or the scoreboard today. The quiz settings page and the quiz-type bar say "applies to the next run" when a run is planned or open, and the run page lists the copied values.

### Option (b) in detail

* Nothing moves; TD-101 is resolved as "decided: live" and TD-036 stays as a known gap.
* `app/api/jinja2/admin/_quiz_type_bar.html` and `app/api/jinja2/admin/quiz_settings.html` show a warning while the quiz has a planned or open run: navigation, reveal, shuffle and sources change for new attempts of that run, and sources change on result pages already shown. The quiz-type overview (`quiz_type_confirm.html`) already warns.

### Consequences

* Good, because every participant of a run gets the same navigation, reveal and shuffle, and a result page keeps its sources
* Good, because one rule covers every run value, and answers visibility follows what the run stores (TD-036)
* Good, because the open-run clash checks become checks on the run's own copy
* Bad, because an admin can no longer fix a wrong reveal or navigation in a running run; closing and opening a new run is the only way
* Bad, because a migration and a new run field, and the plan page and the run page each grow by one read-only block
* Neutral, because [ADR-0041](0041-draw-rows-and-flow-settings.md)'s "effective for new attempts at once" becomes "effective for the next run"; on acceptance ADR-0041 gets an addendum pointing here
* Neutral, because [AC-18](../acceptance-criteria.md) is reworded on acceptance: "Planning or opening a run with a visible scoreboard or rewards while the quiz reveals answers after each question is refused with an explanation; in a run without them the participant sees the solution after each question." The check moves from the settings form to the run, the rule itself does not change

### Confirmation

On acceptance: tests that a settings change and a quiz-type change after opening do not change a new attempt's flow or a finished attempt's sources, that a new run picks the change up, that visibility follows the run's profile, that test links still follow the quiz, and that the data migration fills existing runs.

## More Information

TD-101, TD-036; [OQ-15](../open-questions.md); `docs/superpowers/specs/2026-11-12-quiz-types-design.md`, `docs/superpowers/specs/2026-11-12-test-add-ons-design.md`.

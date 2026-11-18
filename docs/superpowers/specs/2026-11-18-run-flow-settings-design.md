# A run keeps its flow and sources settings — design

Status: decided with the owner in chat on 2026-11-18 (TD-101). Not implemented.

## Why

A run copies most of its behaviour from the quiz when it is planned or opened (time limit,
participants, data profile, scoreboard, rewards) and keeps it. Five quiz settings are still read
live from the quiz while the run is open:

- navigation (`navigation_mode`, `page_size`), reveal (`reveal_moment`, `reveal_level`) and shuffle
  (`shuffle_questions`, `shuffle_options`) — `settings.flow(run.quiz)` at every attempt start
  (`app/domain/attempts.py:237`). An attempt freezes them in `attempt.settings_json` when it
  starts, so an attempt in progress is safe, but a settings change during an open run makes later
  attempts of the same run play by other rules;
- sources (`show_sources`, quiz level; a question's own value is part of the revision) — read live
  on result pages (`app/api/rendering.py:256`), so a change alters result pages of finished
  attempts too;
- `rewards.conflicts` checks reveal against the live quiz (`app/domain/rewards.py:~211`).

A quiz type change or a change of the global settings has the same effect for quizzes that inherit.

## Decisions (the owner's)

1. **Copy, no plan UI.** A run copies these values from the quiz when it is planned or opened, like
   the other run values, and reads them from the run from then on. The run plan form does not get
   new fields.
2. **A change during a run is offered for the running run.** When an admin saves quiz settings that
   change one of these values while the quiz has an open or planned run, the admin is asked whether
   the change applies also to that run (its new attempts and, for sources, its result pages) or only
   from the next run. Finished attempts keep the navigation, reveal and shuffle they were played
   with in any case (they are frozen in the attempt).

3. **Which save paths ask.** The quiz settings page and a quiz type change (apply or remove) ask
   as in decision 2 — both change one quiz. A change of the global settings never changes a
   planned or open run: it applies from the next run of each inheriting quiz, and the global
   settings page says so in one sentence.

## Decided by the agent (owner may change)

- **Which runs are asked about:** the quiz's open run and its planned runs. Test runs (test
  links) have no plan and keep following the quiz as it is now. Ended and archived runs are never
  asked and keep their values.
- **"From the next run only"** leaves planned runs on their old values too. Editing a plan
  (`run_schedule.update_plan`, which re-copies rules, data and results) must not re-copy these
  values — a plan edit would otherwise undo the admin's choice; a test pins it.
- **A change that would conflict with the run's rewards** (for example reveal after each question
  in a run whose rewards need answers kept, as `rewards.conflicts` / `ensure_allowed` decide):
  the question offers only "from the next run", says why, and the quiz change itself is saved;
  the run stays as it is. Nothing is saved half.
- **The answer is a confirm page** like the existing ones (cancel = back to the settings page
  with nothing saved), shown only when a changed value differs from what an affected run holds.

## Goals

- New run field holding the copied values (a JSON field on `QuizRun`, like `results_json`), a
  migration that fills it for existing runs from the quiz's current values (what they read today),
  and every reader (attempt start, result-page sources, rewards conflicts) reading the run.
- The quiz settings page asks, as described in decision 2, and applies the answer.
- Preview (`app/domain/preview.py`) and test links (`app/domain/run_links.py`, kind TEST) keep
  following the quiz as it is now — they have no plan.
- A new ADR (next free number) records the decision; TD-101 is resolved; AC for the behaviour.

## Non-goals

- No run-plan fields for these settings.
- No change to what an attempt already freezes.
- No change to question-level values (they are in the revision snapshot).

## Anti-goals

- A finished attempt's result page changing because the quiz changed (unless the admin applied
  the change to that run on purpose — then sources follow the run).
- An admin silently changing a running run: the question must be asked before anything changes.
- A planned or open run losing its values when the quiz type changes.

## Constraints

- Settings inherit global → quiz → question (ADR-0042); the run stores the resolved quiz-level
  values, a question's own value still wins where it has one.
- Revision switches keep the run's values.
- Migrations reversible where the project's migrations are; data migration fills from current quiz
  values.
- Docs in English; tests first; `make quality`.

## Left to the builder

- The name and shape of the run field and its helper (`flow.of(run)` or similar).
- How the confirmation is shown (a confirm page like the existing ones, or an inline choice).

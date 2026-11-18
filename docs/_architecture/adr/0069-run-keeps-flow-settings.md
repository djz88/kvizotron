---
status: accepted
date: 2026-11-18
---

# ADR-0069: A run keeps its flow and sources values from when it was planned or opened

## Context and Problem Statement

A run copies most of its behaviour from the settings when it is planned or opened: time limit, participant rules, data profile, scoreboard and rewards. Navigation, page size, reveal moment and level, shuffling and sources were still read live from the quiz while the run was open, so a settings change, a quiz type change or a global change during an open run made later attempts play by other rules, and finished attempts changed their result pages (TD-101). Before this, [ADR-0041](0041-draw-rows-and-flow-settings.md) had these settings apply to new attempts at once. [ADR-0064](0064-run-copies-flow-and-profile.md) proposed copying these values and more; this decision takes the part the owner decided on 2026-11-18 and leaves answers visibility to that proposal.

## Decision Drivers

* A run behaves the same for every participant from opening to closing
* One rule for every run value: it is copied when planned or opened
* An admin is asked before a running run changes, not told afterwards
* Test links keep following the quiz ([ADR-0044](0044-preview-and-test-links.md))

## Considered Options

* (a) Copy the seven values onto the run and read them from there; a change to a planned or open run is offered when the admin saves the quiz
* (b) Keep reading them live and warn

The run's own Settings tab does not edit these values: the owner decided there is no plan UI for them, and a run takes a change only through the offer when the quiz changes.

## Decision Outcome

Chosen option: (a).

* `QuizRun.flow_json` holds the seven resolved values `navigation_mode`, `page_size`, `reveal_moment`, `reveal_level`, `shuffle_questions`, `shuffle_options` and `show_sources`, copied by `run_schedule.plan` and `authoring.open_run` (`run_flow.snapshot`). The run plan form gets no new fields.
* Editing a plan (`run_schedule.update_plan`) and switching the run to a newer revision keep the values.
* A test run has no plan: `run_flow.of` reads the quiz live for it. A missing key, or a stored value the catalogue no longer offers, is resolved from the quiz.
* A change to these values when an admin saves quiz settings or changes the quiz type asks whether the planned or open run takes it, or only the next run; a global change applies from each quiz's next run and never changes a planned or open run. The planned run and the open run are the ones asked about; ended and archived runs keep their values. If the run's own rules forbid the change (for example reveal after each question with a visible scoreboard or rewards), only the next run is offered. Nothing is saved half.
* Module requirements ([ADR-0034](0034-module-requirements-on-settings.md)) are judged for a run against its kept values, not the quiz's: planning and opening judge them so, and publishing a revision whose requirements a run's values do not meet leaves the run on its revision (a planned run too), as it already does for a stateless run and a photo question; refusing would leave no way to publish after an earlier "next run" answer. The editor's "Use" button is a quiz settings change and asks like any other.
* The migration `0028` fills existing runs with what their quiz reads today.

### Consequences

* Good, because a competition cannot change under its participants.
* Good, because every run value follows one rule.
* Neutral, because [AC-18](../acceptance-criteria.md) is reworded: planning or opening a run with a visible scoreboard or rewards while the run reveals answers after each question is refused, and a run-level clash no longer blocks saving a quiz or global setting; it only limits the offer to "next run".
* Neutral, because the readers (attempt start, result sources, the reveal checks of plan, open, display and rewards conflicts) read the run, and a quiz settings save or a quiz type change asks the admin (offer and answer) whether the planned or open run takes the change. Removing a quiz type never asks, because it changes no value.

---
status: accepted
date: 2026-11-12
---

# ADR-0062: Quiz types as named bundles of quiz settings behind a `quiz_type` port

## Context and Problem Statement

An admin who wants a pub quiz, a practice quiz or a contest has to know which of about 40 settings to change and how they combine. The common kinds of quiz can be built from settings the application already has ([ADR-0042](0042-settings-inherited-and-declared.md)). A quiz type sets them in one step and keeps telling the admin where the quiz no longer follows it. Open were where the definitions live, whether another module can add a type, and where the rules of applying a type belong.

## Decision Drivers

* A type sets only existing quiz settings with values the settings form also accepts; nothing new for a run or an attempt
* Another module can add a type without a change in the core ([ADR-0037](0037-providers-and-plugins.md))
* A wrong definition fails in the tests, not when an admin applies it
* Plugins import only `app.contracts`; storage, transactions and the rules between settings stay in the domain
* No new setting and no new dependency

## Considered Options

* A port `quiz_type` with a plugin that holds only the definitions; the domain applies them
* A fixed table of types in the domain
* Presets on each module that owns a setting, merged at run time

## Decision Outcome

Chosen option: "A port `quiz_type` with a plugin that holds only the definitions; the domain applies them", because a module can add a type the same way it adds a question type, and the rules of applying stay in one place beside the settings they protect.

* **The port.** `QuizTypePlugin` (port `quiz_type`) has `id`, `version`, `order` (position in lists, ascending), `resets_all`, `label()`, `description()` and `values()`, a mapping of setting key to value. Every key is a setting the quiz may override and every value one of its choices. Only a type that resets has `resets_all` set, and its `values()` is empty.
* **The plugin.** `quiz_types.basic` (`app/plugins/quiz_types/`) registers six types: `practice`, `final_test`, `mock_test`, `contest`, `pub_quiz` and `basic`. Their values are the table in [plugins/quiz-types.md](../plugins/quiz-types.md). `basic` removes every quiz override, so the quiz follows the global settings again; the quiz's colour palette is a quiz setting and goes too (the overview lists it). The module declares no settings and is not always on.
* **Definitions only.** The plugin does not read or write settings. Which overrides a quiz gets, the deviations from the type, the clashes with other settings or with runs, the overview before a change and the audit belong to a domain service, like the split of `results.local` ([ADR-0051](0051-scoreboard-participants-and-official-attempt.md)) and `rewards.threshold` ([ADR-0053](0053-rewards-tiers-alternates-and-draw-history.md)).
* **The contract suite** `tests/contracts/quiz_type.py` checks every type of a module against the settings catalogue: each key is a quiz setting, each value is offered, the values with the defaults for the rest pass the clash rules of the settings forms (`setting_rules.clashes` in `app/domain/setting_rules.py`, leaving out the clashes with planned or open runs, which depend on runs), a type that resets has no values, and the orders are unique.

### Consequences

* Good, because a module can add a type, and a definition that names an unknown key or value fails the contract suite
* Good, because a type writes ordinary quiz overrides, so playing, runs and exports change nothing
* Bad, because the core setting keys are spelled as strings in the plugin, which may not import the domain; the contract suite catches a rename
* Bad, because a later change of a type's definition does not reach quizzes that applied it; they only show the deviation

### Confirmation

`tests/contracts/test_quiz_types.py` runs the suite on the six types and checks each type's values against the table.

## More Information

Design: `docs/superpowers/specs/2026-11-12-quiz-types-design.md`. Types the admin saves from a quiz are TD-100, a poll type TD-099, other kinds of quiz TD-094 to TD-098, and copying the live settings to an open run TD-101.

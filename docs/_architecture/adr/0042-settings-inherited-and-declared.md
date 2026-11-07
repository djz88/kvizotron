---
status: accepted
date: 2026-11-07
---

# ADR-0042: Settings are inherited global → quiz → question, and every module declares its own

## Context and Problem Statement

Settings had a global value and a quiz override, and they were listed only in the domain. External images need a value per question, and more settings will come from modules. Nothing made anyone decide where a new setting fits, so each one could end up with a different shape.

## Decision Drivers

* The same chain everywhere, so an admin always knows where a value comes from
* A decision nobody can skip, whether made by a person or an agent
* Manifests stay plain data that load before Django

## Considered Options

* A required `settings` field and a default chain of three levels, with a written reason for anything narrower
* An optional field, checked in review
* Global and quiz by default, with the question level on request

## Decision Outcome

Chosen option: "A required `settings` field and a default chain", because a test fails when the decision is missing.

- A setting is a value inherited along the chain. Question content such as points, scoring strategy or sources is not a setting.
- The default scopes are `global`, `quiz`, `question`. A narrower scope needs a reason in the declaration.
- Every manifest, of plugins and providers alike, has a required `settings` field. A module with none states `[]`.
- Whoever adds a setting decides where it fits. An agent asks the user unless the task already says.
- `settings.resolve(key, quiz, question)` returns the question value, else the quiz value, else the global value, else the default. A stored value no longer offered is skipped.
- A question value lives in the question's `settings`, next to `points`, and only when set. So it belongs to the revision, and a changed value makes a draft. A quiz or global value does not.
- A module's settings join the catalogue at start-up and go with it. A key owned twice stops the start.
- A question type lists the question-level settings that affect it in `question_settings()`. `show_sources` applies to every type.
- `settings_requirements` ([ADR-0034](0034-module-requirements-on-settings.md)) stays. It says what a module needs from settings, while `settings` says what a module owns.

### Consequences

* Good, because `tests/contracts/test_settings_rule.py` reads the real forms, so a declared scope without a working field fails
* Good, because labels live with their setting, wherever it comes from
* Bad, because every manifest has one more line, even with nothing to say

### Scope of the existing settings

`show_sources`, `shuffle_options` and `none_option` gained the question level. `navigation_mode`, `reveal_moment`, `reveal_level`, `shuffle_questions`, `color_palette` and `revision_switch_policy` stay global and quiz, each with its reason in `app/domain/settings.py`.

---
name: kvizotron-add-module
description: Use when adding a new Kvízotron plugin or provider, a new question type, scoring strategy, theme or infrastructure backend, or when a feature would otherwise go into the kernel.
---

# New module

A feature belongs in a module behind a contract (ADR-0037). Patterns that run and are guarded by tests:

| What you are building | Copy from |
|---|---|
| Question type | `app/plugins/questions/number/` |
| Module outside this repository | `tests/fixtures/demo_site/kvz_demo_question/` |
| Provider | `app/providers/csv_io/` |

## 1. Before you start

- **Plugin or provider?** Features that are switched on at run time are plugins. Infrastructure chosen at startup is a provider.
- **Does the port exist?** Protocols are in `app/contracts/`. A new port is a decision: it needs an ADR and a shared suite in `tests/contracts/`.
- **Does it have settings of its own?** **REQUIRED SUB-SKILL:** `kvizotron-add-setting`. Without settings the manifest says `"settings": []`.

## 2. Files

In the module directory:

- `manifest.py` without importing Django: it runs while the configuration is loaded. `id`, `kind`, `version`, `app`, `api_compatibility`, `provides`, `requires`, `settings`.
- `apps.py`: in `ready()` it calls `registry.register(<port>, <key>, <object>, <module id>)`. The fourth argument is the `id` from the manifest.
- Templates in `jinja2/<name>/`, texts in `locale/`.
- It imports only `app.contracts` and `app.kernel`. Plugins are invisible to each other.

## 3. Wiring

Each point is guarded by a test in `tests/test_wiring.py`:

1. A line in `[project.entry-points."kvizotron.modules"]` in `pyproject.toml`. Then `make setup`, otherwise the environment does not see the module.
2. If it has texts: a directory in `ROOTS` in `tools/messages.py`, then `make messages` and filled `msgstr` in cs and uk.
3. A shared suite in `tests/contracts/`. A question type has `test_<type>.py`, which inherits `QuestionTypeContract`.
4. Documentation: `docs/_architecture/plugins/` or `providers/` with the module's name, a question type in `docs/_architecture/plugins/question-types.md`.
5. New requirements and decisions: the `FR-xx` map in `docs/_architecture/README.md`, possibly an ADR.

## 4. What a test will not catch

- `describe_definition` must change its output when any field of the definition changes, otherwise the change overview does not show it. The same holds for a new field added later.
- A new question type changes the count in `tests/contracts/test_demo_question.py` when you add a test to `tests/contracts/question_type.py`.
- Switching a plugin off at run time: an old revision with its questions must still be gradable (`include_disabled`).
- Own tables have a migration in the module. Domain tables are not edited.

## 5. Done

**REQUIRED SUB-SKILL:** `kvizotron-check-applied`.

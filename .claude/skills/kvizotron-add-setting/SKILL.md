---
name: kvizotron-add-setting
description: Use when adding, moving or changing the scope of a setting in Kvízotron, including a request phrased as a switch, an option, or "let the admin choose", and when a module needs a value an admin can set.
---

# Adding a setting

The rules are in ADR-0042. Here are the order and the places the test does not remind you of by itself.

## 1. Before you write code

Is it a setting at all? A value that is inherited is. The content of a question (points, sources, strategy) is not.

Ask the user through `AskUserQuestion`, unless the request says it explicitly:

- **Scope.** The default is global → quiz → question. Offer a narrower one only with a concrete reason, which then goes into `scope_reason`.
- **Default value**, if it changes the behaviour of existing quizzes.

Choose the group and level (`group`, `level`) yourself and state them in the message: the group by what the setting concerns (`playing`, `answers`, `participants`, `scoreboard`, `rewards`, `data`, `look`, `technical`), the level `basic` only for what an admin changes in most quizzes. Without them the setting is `technical` and `advanced` (ADR-0052).

Haste or "I'll look at it later" does not cancel this question. Scope is changed badly in stored data and imports. If you cannot ask, stop and write the question; do not choose the scope for the user.

## 2. Where it belongs

| Owner | Where |
|---|---|
| Domain | a constant, possibly a `StrEnum`, and a `CATALOGUE` entry in `app/domain/settings.py` with `group=` and possibly `level=BASIC` |
| Module | the `settings` field in its `manifest.py`, the pattern is in `app/plugins/questions/image_answer/manifest.py` |

Question scope needs one more of these:

- a question type returns the key in `question_settings()`,
- it applies to all types: `ALL_TYPES_QUESTION_SETTINGS`.

## 3. Reading the value

- Always `settings.resolve(key, quiz, question)`. `AppSetting` is not read directly.
- A plugin does not read settings: it receives them in `quiz_settings` from the API.
- Decide when the value is read and write it down: on every page load, at the draw (`none_option`), or copied to the run (`attempt_limit`).

## 4. What to go through, depending on what the setting affects

| Question | Where |
|---|---|
| Does the participant see it? | `app/api/play.py`, and likewise the preview: `app/domain/preview.py`, `app/api/admin_preview.py` |
| Should a test link behave the same? | `app/domain/run_links.py` |
| A value of a kind other than a choice? | the forms in `app/api/admin_forms.py` have exceptions, the pattern is `ATTEMPT_LIMIT` |
| Does it exclude another setting? | `is_flow_conflict`, `is_visibility_conflict` in `settings.py`; a module through `settings_requirements` |
| Is it on a question? | It belongs to the revision, a change makes a draft. Go through `app/domain/revision_diff.py`, `app/domain/question_import.py`, `app/domain/question_export.py` |

## 5. It is done when

- Tests show inheritance at every offered scope, deleting an override, and the real effect on the page, not just the stored value.
- `make messages` ran and `msgstr` in cs and uk are filled.
- `docs/_architecture/modules/api-ui.md` lists the setting in the "Where things are set" table. A module also in its file in `docs/_architecture/plugins/` or `providers/`. New behaviour has an `AC-xx` row.
- `make quality` passed. `tests/contracts/test_settings_rule.py` guards the scopes and form fields, `tests/test_wiring.py` that someone reads the value. Whether it has an effect, verify through `kvizotron-check-applied`.

## Common mistakes

| Mistake | Correct |
|---|---|
| A narrower scope because it is faster | Speed is not a reason for `scope_reason`. Ask. |
| A choice without a label in `value_labels` | Validation rejects it. Every choice has a translated label. |
| An effect only in `play.py` | The preview shows different behaviour than the run. |
| A test only on `resolve` | The test must also see the page the setting changes. |

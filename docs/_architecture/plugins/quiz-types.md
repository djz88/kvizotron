# Plugin: quiz types (quiz_types.basic)

| | |
|---|---|
| Contract | `QuizTypePlugin` |
| Package | `app/plugins/quiz_types/` |
| Stage | after D5 |
| Decision | [ADR-0062](../adr/0062-quiz-type-port.md) |

## Behaviour

- A quiz type is a named bundle of quiz settings. The plugin holds only the definitions; applying a type to a quiz, its deviations and its clashes belong to the domain ([ADR-0062](../adr/0062-quiz-type-port.md)).
- Each type is registered under its id (port `quiz_type`, owner `quiz_types.basic`) and lists by `order`, ascending. `values()` returns a copy of the type's setting key → value mapping.
- The module declares no settings and is not always on.

## The types

Keys not listed follow the global settings. "–" means the type does not set the key. `attempt_limit` is in minutes, `0` is no limit; `pass_mark` is a percentage; `max_attempts` 0 is no limit.

| Setting (key) | `practice` | `final_test` | `resit_exam` | `mock_test` | `contest` | `pub_quiz` |
|---|---|---|---|---|---|---|
| navigation_mode | step_no_back | step_no_back | step_no_back | step_back | step_back | pages |
| page_size | – | – | – | – | – | 10 |
| reveal_moment | after_each | never | after_close | at_end | never | at_end |
| reveal_level | explanations | – | explanations | explanations | – | answers |
| shuffle_questions | on | on | on | on | on | off |
| shuffle_options | on | on | on | on | on | off |
| attempt_limit | 0 | 30 | 30 | 30 | 0 | 0 |
| repeat_attempts | allow | forbid | allow | allow | forbid | forbid |
| max_attempts | – | – | 2 | 0 | – | – |
| after_pass | – | – | more | – | – | – |
| ask_name | off | required | required | off | required | required |
| ask_when | – | start | start | – | end | start |
| ask_email | off | off | off | off | required | off |
| duplicate_names | – | allow | allow | – | forbid | forbid |
| scoreboard_visibility | hidden | hidden | hidden | hidden | after_end | live |
| official_attempt | – | first | best | – | first | first |
| pass_mark | – | 70 | 70 | 70 | – | – |
| reward_source | – | – | – | – | quiz | – |
| winner_contact | – | – | – | – | require_email | – |
| data_profile | score | answers | answers | score | score | score |
| answers_visibility | – | – | participant | – | – | – |
| show_sources | on | off | off | on | off | on |

Names (en / cs): Practice / Procvičování, Final test / Závěrečný test, Exam with a resit / Zkouška s opravným pokusem, Mock test / Zkouška nanečisto, Contest / Soutěž o ceny, Pub quiz / Hospodský kvíz, Basic quiz / Jednoduchý kvíz; uk through the module's catalogue.

- `basic` (Basic quiz) sets no values and has `resets_all`: it removes every quiz setting override, so the quiz follows the global settings again. It does not touch branding.
- `resit_exam` (order 25, between Final test and Mock test) is an exam with a pass mark and two attempts, the better one kept, answers shown after the run closes ([AC-172](../acceptance-criteria.md) to [AC-175](../acceptance-criteria.md)). Final test sets `pass_mark` 70, Mock test sets `pass_mark` 70 and `max_attempts` 0, and only `resit_exam` sets `after_pass`; the other types set none of the three new keys.
- `contest` sets the rules only; the prize is added on the Rewards tab, and its description says so. The access code belongs to a run and is in no type.
- `pub_quiz` is one phone per team, with the team name as nickname and ten questions per page. The catalogues avoid the word for a round, which was the old word for a run.

## Contract suite

`tests/contracts/quiz_type.py` (`QuizTypeContract`): each key is a quiz setting, each value one of its choices, the values pass the clash rules of the settings forms, `app/domain/setting_rules.py` (with the defaults where the type sets nothing; clashes with planned or open runs depend on runs and are left out), a type with `resets_all` has no values, and orders are unique. `tests/contracts/test_quiz_types.py` checks the table above exactly.

## Not here

Types saved by an admin (TD-100), a poll type (TD-099), other kinds of quiz (TD-094 to TD-098). See [TECH_DEBT.md](../TECH_DEBT.md).

# Quiz types — design

Date: 2026-11-12. Status: approved 2026-11-12. Project A of four (A quiz types, B test add-ons, C contest rules, D practice add-ons), in that order.

## Why

An admin who wants a pub quiz, a practice quiz or a contest has to know which of about 40 settings to change and how they combine. Research (pub quizzes, Kahoot, Moodle, Canvas, Microsoft Forms, Wayground, consumer contests) showed that the common quiz types can be built from settings the application already has. A quiz type sets them in one step and keeps telling the admin where the quiz no longer follows it.

## What (the user's choices)

### Choosing a type

- **New quiz form**: a collapsed disclosure "Quiz type ▸" with the list of types, each with a one-line description. Closed or untouched, the quiz is created as today, without a type (the default).
- **Quiz settings page**: a bar at the top "Type: Final test · Deviations: 2" (a count without plural forms) with **Apply again**, **Change type ▾** and **Remove type**; without a type, a way to choose one.
- Each field whose value differs from the type has a small mark "▲ type: 30 min" next to it.

### What a type does

- It writes its values as ordinary quiz settings (quiz overrides), and the quiz remembers the type's id.
- Deviations are counted against the type's **current** definition: a field differs when the value the quiz resolves to (its override or the global value) is not the type's value. Keys the type does not set are never deviations.
- When a new version of the application changes a type's definition, existing quizzes keep their values; they only show the deviation and can **Apply again**.
- **Changing the type** and **Apply again** first show an overview of what will change (field, current value, new value), and the admin confirms.
- **Changing the type** also returns to the global value every key the old type sets and the new one does not (for example Contest → Practice removes `reward_source`, `winner_contact`, `duplicate_names`, `official_attempt`, `ask_when`); the overview lists them as "back to the global value". Which keys the old type sets is read from its current definition.
- **Remove type** forgets the type and keeps every value.
- **Running runs**: as with a manual change today, part of the values is copied to a run when it is planned or opened (time limit, participants, data profile, scoreboard, rewards) and part is read from the quiz at each attempt start (navigation, page size, reveal, shuffle) or when a page is drawn (sources). A planned or open run therefore keeps the copied values but uses the new live ones for new attempts; the overview warns about this when the quiz has a planned or open run. Copying the live values to the run is TD.
- **Clashes**: a type's values can clash with other settings of the quiz or with its runs (the cross-field rules of the settings form in `app/api/admin_forms.py`). A clash with another quiz setting is resolved by the type: that setting is set to a value that goes with the type (for example `answers_visibility` back to `admins` under the `score` profile, duration columns off without the `detailed` profile), shown in the overview. A clash with a planned or open run (for example reveal after each question while a run has a visible scoreboard, AC-18) refuses the type with the same message the settings form gives. The same rules apply on the new-quiz form, where a new quiz has no runs.
- **Duplicating a quiz** now copies its type and all its quiz settings (overrides). Branding is still not copied.

### The types

Keys not listed follow the global settings. "–" means the type does not set the key.

| Setting (key) | Practice | Final test | Mock test | Contest | Pub quiz |
|---|---|---|---|---|---|
| navigation_mode | step_no_back | step_no_back | step_back | step_back | pages |
| page_size | – | – | – | – | 10 |
| reveal_moment | after_each | never | at_end | never | at_end |
| reveal_level | explanations | – | explanations | – | answers |
| shuffle_questions | on | on | on | on | off |
| shuffle_options | on | on | on | on | off |
| attempt_limit (minutes) | 0 | 30 | 30 | 0 | 0 |
| repeat_attempts | allow | forbid | allow | forbid | forbid |
| ask_name | off | required | off | required | required |
| ask_when | – | start | – | end | start |
| ask_email | off | off | off | required | off |
| duplicate_names | – | allow | – | forbid | forbid |
| scoreboard_visibility | hidden | hidden | hidden | after_end | live |
| official_attempt | – | first | – | first | first |
| reward_source | – | – | – | quiz | – |
| winner_contact | – | – | – | require_email | – |
| data_profile | score | answers | score | score | score |
| show_sources | on | off | on | off | on |

Names (cs / en): Procvičování / Practice; Závěrečný test / Final test; Zkouška nanečisto / Mock test; Soutěž o ceny / Contest; Hospodský kvíz / Pub quiz (one phone per team, the team name as nickname, ten questions per page; its description does not use the word round/kolo, which the texts of the application avoid); uk translations through the catalogues.

**Basic quiz** (Jednoduchý kvíz / Basic quiz) is a sixth type: it removes every quiz setting override, so the quiz follows the global settings again. Its deviations are the overrides the quiz has. It does not touch branding.

The Contest type sets the rules only; the prize (reward rule and its text) is added by the admin on the Rewards tab, and the type's description says so. The access code belongs to a run and is not part of any type.

## Not in scope

- Types the admin saves from a quiz (custom types): TD-100.
- A poll type (questions without a right answer, no score): TD-099.
- Copying navigation, reveal, shuffle and sources to a run when it opens: TD-101.
- Live game led by a host, full pub quiz, course with unlocking and certificate, personality quiz, trail with QR stations: TD-094 to TD-098.
- The add-ons of projects B, C and D (pass mark, number of attempts and kept score, reveal after the run closes, contest rules and consent, retry until right, wrong questions again at the end, hints). Each project adds its values to the types when it lands.

## Calls made here (Claude's, for the user to check)

- Types come from a new plugin through a new contract, so another module can add types; the plugin holds only definitions, the rules for applying them live in a domain service (`app/api/CLAUDE.md`: no rules in the API).
- Applying a type writes all its values in one transaction with one audit entry for the type (`quiz.type_applied`, `quiz.type_removed`, ids only) besides the existing per-setting entries.
- A key of a disabled module (for example rewards off on the Modules page) is skipped, and the overview says so.
- When the quiz's content does not go with a type's values (a photo question with Practice's reveal after each question), the overview warns; the type is still applied and the existing check at planning still refuses the run with its message. Content is not a setting the type can adjust, unlike the clashes above.
- The clash rules of the settings form become domain rules used by both the form and the type service, so the two cannot disagree.
- Values a type writes must pass the same choice checks as the settings form; a type definition with an unknown key or value fails the contract tests, not at runtime.

## Left to the builder

- Where the quiz's type id is stored (a field on `Quiz` with a migration, or elsewhere) and how the contract is shaped; follow `QuestionTypePlugin.presets()` as the nearest precedent and `kvizotron-add-module`.
- The layout of the new-quiz disclosure, the settings bar and the marks, within the existing admin patterns (Pico, no inline scripts or styles, CSRF on every POST, works without JavaScript).
- Acceptance criteria (next free AC), an ADR for the contract, docs for the plugin in `docs/_architecture/plugins/`, cs and uk strings.

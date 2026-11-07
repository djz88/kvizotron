# B1 Revisions: design

Status: approved 2026-11-06. Marks: **[user]** decided by the user, **[call]** the author's call, open to correction.

## Why

Admins must be able to change a quiz safely while people are playing it, see what they are about to
publish, and undo a mistake, all without rewriting history. A4 already delivered immutable revisions,
the `DRAFT → PUBLISHED → SUPERSEDED` path, publication blocked by missing translations, and attempts
pinned to one revision (AC-04 has a test). B1 adds what is missing around them.

## Stage B scope changes

Decided by the user in the same conversation, recorded in `roadmap.md` as part of this milestone:

| Addition | Milestone |
|---|---|
| Change overview before publication, return to an older revision, discard a draft | B1 |
| Warning about unsaved editor changes; TD-010 and TD-011 resolved before the new question types | B2 |
| Translated explanation of the correct answer, shown when solutions are revealed | B3 |

Order stays B1 → B5. Each milestone gets its own design and plan.

## Goals

1. Decide what happens to an open round when a new revision is published, by a setting.
2. Global settings page with per-quiz override, reusable by later milestones.
3. Change overview before publication.
4. Return to an older revision; discard a draft.
5. FR-08 remainder: duplicate and archive a quiz, revision list, historical rounds.
6. `ARCHIVED` revision state.

## Non-goals

- Scoreboard consequences of several revisions in one round (ADR-0008): Stage C.
- Time limits and deadlines: C1. This design only keeps start time intact for them.
- Formatting of question text, hints, per-question time limits: rejected for now.
- Selecting or comparing arbitrary pairs of revisions: only draft against published, and each revision against its predecessor.

## Anti-goals

- A published revision is changed, or an attempt is re-evaluated against another revision.
- A participant loses answers to questions that did not change.
- Switching a revision gives a participant extra time.

## 1. New revision during an open round

### Setting **[user]**

`revision_switch_policy`, set globally, overridable per quiz:

| Value | New participants | Participants in progress |
|---|---|---|
| `ask` (global default **[call]**) | decided at publication | decided at publication |
| `notify_switch` | new revision | see a notice; "Switch" replaces the button that moves forward |
| `let_finish` | new revision | finish on the old revision |

With `ask`, the publication page offers `notify_switch`, `let_finish` (preselected **[user]**) and
`stay`. `stay` keeps the whole round on the old revision; the new one applies from the next round. It
is offered only at publication, never as a stored policy **[call]**. If no round is open, the policy
plays no part and nothing is asked.

`stay` writes no `RunRevision` row and changes nothing about the round, including earlier switch decisions
**[call]**. If the round moved to revision 2 with `notify_switch` and revision 3 is published with `stay`,
attempts on revision 1 still get the notice and switch to revision 2.

### Round and revision

- Add `RunRevision` per `data-model.md`: `run`, `revision`, `active_from`, `active_to`, `max_score`, plus
  `switch_mode` (`finish` or `switch`). The first row is created when the round opens; a data migration
  creates rows for existing rounds. A first row has `switch_mode=finish` **[call]**.
- `QuizRun.current_revision` stays the pointer that new attempts use.
- Publication and the switch of the round happen in one transaction and are audited with the chosen mode.
- The current row's `switch_mode` applies to every older in-progress attempt: the last decision wins **[call]**.
- `app/domain/usage.py` must consider every revision of an open round, because old attempts are still
  in play. Today it checks only `current_revision`.

### Notice for the participant

- While playing, an HTMX element asks `GET /a/{attempt_id}/revision-status` every 30 seconds **[user]**.
  The response is empty unless the attempt must switch. It then contains the notice and an out-of-band
  swap replacing the submit button with "Switch". Status 286 stops polling when the round has closed.
- Attempt ids are not secrets and the response reveals only that a newer version exists, so no token is
  needed **[call]**.
- For a `SWITCHED` attempt, for example in a second tab, the response is always the notice and "Switch" **[call]**.
- It is a page rule, not a security boundary, as with "no going back" (ADR-0035). A modified or JavaScript-free
  client can still submit the old attempt, and the server evaluates it against the old revision (AC-04).
- B1 has only the all-at-once page, so the submit button is replaced. B3 applies the same rule to "Next".

### Switching

`POST /a/{attempt_id}/switch` with `attempt_token` and the current answers; `csrf_exempt` like start and submit.

- Verified like submit: token, run, revision and manifest. The attempt must be in progress and the round open.
- A new `Attempt` is created on the current revision. The old one gets the new status `SWITCHED` and
  `replaced_by`. It stays unsubmitted **[user]** and cannot be submitted any more: this answers 409 with a
  translated message **[call]**, so one person cannot get two results from one start. `SWITCHED`
  attempts count in no result.
- The new attempt inherits `started_at` and expiry from the old one **[call]**, and `duration_ms` runs from that time.
- A repeated request on a `SWITCHED` attempt follows `replaced_by` to the end of the chain **[call]** and
  returns that attempt with a fresh token and submission key, so a double click creates only one attempt.
  If the end of the chain is already submitted, it answers 409 "already submitted".
- If the round is already back on the attempt's revision, nothing changes and the page is re-rendered.
- Works without HTMX too: a whole page, as with start and submit.

### Moving answers **[user]**

- A question keeps its answer if the id, the type and the `definition` are equal in both revisions. A
  correction of one option's text therefore counts as a change.
- Points, scoring strategy and type version may differ **[call]**: the answer is still what the participant
  meant, and the new revision scores it. The participant sees no mark, but the change overview lists them.
- A kept answer must pass `validate_submission` on the new revision, otherwise it is dropped.
- Changed questions are empty and marked "This question changed". Removed ones disappear, new ones are empty.
- Contract change: `render_public(public_config, locale, answer=None)` shows a given answer. The contract
  suite tests it for every question type, including escaping.

## 2. Settings

- New table `app_setting` (`key`, `value_json`, `quiz` nullable) with one row per key and scope; owner: domain **[call]**.
- A small code catalogue defines each setting: key, allowed values, default, translated label. Unknown
  keys and values are refused. `resolve(key, quiz)` returns quiz override → global → default.
- `/admin/settings` lists global settings. The quiz form shows an override: "Use global setting (now: X)" or one of the values.
- Changes are audited.
- This table is for application settings. `plugin_configuration` in `data-model.md` remains the plan for
  module configuration (D4). B2's module requirements (FR-46) may refer to these keys.

## 3. Change overview

- The publish button leads to `GET /admin/quizzes/{id}/publish`, which shows problems blocking publication,
  the changes, and the outcome for an open round (or the `ask` choice). `POST` publishes as today.
- `title`, `supported_locales` and `default_locale` stay on the `quiz` row until publication, as in A4 **[call]**.
- The form carries a hash of the future snapshot: those three fields plus the draft's questions. If it
  changed since the page was shown, nothing is published and the page is shown again, so the admin
  publishes what they saw **[call]**.
- Overview of draft against the latest published revision: title, languages, default language; questions
  added, removed, moved, changed; for changed ones, before and after for each changed row, including
  correct answers, points, scoring strategy and type version.
- Contract addition: `describe_definition(config, locales) -> list[DefinitionRow]`, where a row is a
  translated label, a locale or none, and a plain-text value. The comparison stays generic for all question
  types and is reused by AC-06 in Stage C. The contract suite checks that a change in any definition field
  changes the rows.
- The first publication shows everything as added.

## 4. Older revision and discard

- **Return:** on the revision list, "Use as new draft" creates a draft from any non-draft revision's questions
  and restores `title`, `supported_locales` and `default_locale` from its snapshot. The old revision stays
  untouched and publishing gives a new number. An existing draft is replaced only after a confirmation
  page **[call]**. Question ids stay, so moving answers works on a return too.
- **Discard:** deletes the draft and restores the same three quiz fields from the latest published
  revision, with a confirmation page. A quiz never published has nothing to return to, so discard is refused **[call]**.
- Both are audited. A type no longer available shows up as an ordinary publication problem.

## 5. Quiz management (FR-08)

- **Revision list** `/admin/quizzes/{id}/revisions`: number, status, publication date, question count, max
  score, comparison with the previous revision, "Use as new draft".
- **Historical rounds** on the same page: number, status, opened, closed, revisions used, submitted attempts,
  link to the round.
- **Duplicate:** a new quiz with a new slug (prefilled, editable), the copied title and languages, and a draft of
  the currently editable questions. No revisions, rounds or attempts. `featured` off. New question ids are not needed **[call]**.
- **Archive** (`quiz.archived_at`, `data-model.md`): refused while a round is open, with an explanation
  **[call]**. The quiz disappears from the landing page, its public pages show the existing "unavailable"
  page, and the admin list hides it behind a filter. Its `PUBLISHED` revision becomes `ARCHIVED`.
  It cannot be published or get a new round until restored.
- An archived quiz is read-only in the admin **[call]**: editing, publishing, return and discard are refused.
  An existing draft is kept untouched and is editable again after restore. Duplicate is allowed, and copies
  the draft if there is one, otherwise the highest `ARCHIVED` revision.
- **Restore:** clears `archived_at` and returns the highest `ARCHIVED` revision to `PUBLISHED`. Revisions do
  not have their own archive action **[call]**. The change of status does not change the content, which stays immutable.

## Constraints

- Views stay thin; rules live in `app/domain/`.
- New admin strings in cs and en catalogues, public strings in cs, en and uk.
- Docs in English; each fact in one place. Update `roadmap.md`, `domain.md`, `api-ui.md`, `data-model.md`,
  `contracts.md`, `plugin-api.md`, `CLAUDE.md`. New ADR for the switch policy and the settings table. New `FR-xx`
  and `AC-xx` take the next free numbers.
- Verified in Docker, without a local install: `make quality` and `make smoke`, plus a browser walkthrough
  of publishing during an open round.

## Acceptance (additional to AC-03, AC-04)

- With `notify_switch`, a participant in progress sees the notice within one polling interval; after "Switch",
  answers to unchanged questions are kept, changed ones are empty and marked, and the old attempt can no longer be submitted.
- With `let_finish`, an attempt in progress submits on the old revision while new starts get the new one.
- `stay` leaves the round on the old revision; the next round opens on the new one.
- A quiz override beats the global setting; deleting the override returns to global.
- Switching does not reset `started_at`; a double click creates one attempt.
- The overview shows a changed correct answer; publishing a draft changed after the page was shown is refused.
- Return creates a new number and leaves the old revision byte-identical (checksum unchanged).
- A quiz with an open round cannot be archived; an archived one has no public page and returns on restore.

## Left to the builder

Template layout, exact labels, polling markup, form and URL names not listed here, the shape of `DefinitionRow`
beyond the fields above, and how the catalogue is structured.

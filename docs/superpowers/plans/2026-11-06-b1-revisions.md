# B1 Revisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin decides by a setting what happens to an open round when a new revision is published, sees the changes before publishing, can return to an older revision or discard a draft, and can duplicate and archive a quiz.

**Architecture:** Rules live in `app/domain/` (`settings.py`, `authoring.py`, `attempts.py`, new `revision_diff.py`); `app/api/` holds thin views and templates. The round's revision history is the new `RunRevision`; `QuizRun.current_revision` stays the pointer for new attempts. Question types gain two contract methods, so the overview and moved answers work for every type.

**Tech Stack:** Python 3.15, Django 6.1.3, Jinja2, HTMX 2.0.11, Pico CSS 2.1.1. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-06-b1-revisions-design.md`

## Global Constraints

- All commands run in Docker. `d` is `<scratchpad>/d`; `make smoke` runs on the host. Never report a result as local.
- Branch `stage-b/b1-revisions`. The spec and this plan go in the first commit.
- A published revision's content is never mutated. An attempt is evaluated against the revision pinned at its start. `public_payload()` and everything sent to a participant never contains the answer key.
- Answers and personal data never reach logs or audit details.
- Admin strings in cs and en, public strings in cs, en and uk; source strings English. `d make messages` in every task that adds strings; `tests/test_translations.py` enforces it.
- Admin state changes are CSRF-protected and require login. Public start, submit and switch are `csrf_exempt` and rely on the signed token.
- Docs in `docs/` English; `CLAUDE.md` Czech.
- **Commit only after the exit code is checked to be 0.** Before each commit `d make lint` and `d make test`; before the merge `d make quality` and `make smoke`.

## Review Focus

1. Saving only the quiz override must not create a draft or report unpublished changes. Pinned in Task 1.
2. A switch where the new revision no longer has the participant's language must fall back to the default language, not answer 500. Pinned in Task 4.
3. Polling for an unknown attempt or a closed round must stop quietly, and never swap an error page into the quiz. Pinned in Task 4.
4. The overview and revision list must render when a question's type is no longer installed. Pinned in Task 5.
5. Question and title text with markup must be escaped in the overview; `describe_definition` returns plain text. Pinned in Task 5.

---

### Task 1: Settings with global value and quiz override

**Files:**
- Create: `app/domain/settings.py`, `app/api/admin_settings.py`, `app/api/jinja2/admin/settings.html`, `app/domain/migrations/0002_appsetting.py`, `tests/domain/test_settings.py`, `tests/api/test_admin_settings.py`
- Modify: `app/domain/models.py`, `app/api/admin_urls.py`, `app/api/admin_quizzes.py`, `app/api/jinja2/admin/base.html`, `app/api/jinja2/admin/quiz_edit.html`

**Interfaces:**
- Produces, in `app.domain.settings`: `REVISION_SWITCH_POLICY = "revision_switch_policy"`; `Policy` with `ASK="ask"`, `NOTIFY_SWITCH="notify_switch"`, `LET_FINISH="let_finish"`; `UnknownSetting(Exception)`, `InvalidSettingValue(Exception)`; `CATALOGUE: dict[str, SettingDefinition]` (`key`, `choices: list[tuple[str, lazy label]]`, `default`, `label`); `resolve(key: str, quiz: Quiz | None = None) -> str`; `quiz_override(key, quiz) -> str | None`; `set_global(key, value, *, admin_id) -> None`; `set_override(key, quiz, value: str | None, *, admin_id) -> None` (`None` deletes the override).
- Model `AppSetting`: table `app_setting`, `key` (CharField 80), `value_json`, `quiz` nullable FK (`CASCADE` is not used: `PROTECT`). Two partial unique constraints: `(key)` where quiz is null, `(key, quiz)` where quiz is not null.

- [x] **Step 1: Write failing tests** (`tests/domain/test_settings.py`)

```python
def test_default_when_nothing_is_set():
    assert settings.resolve(settings.REVISION_SWITCH_POLICY) == "ask"

def test_global_value_beats_default(): ...      # set_global → resolve(key) == "let_finish"
def test_quiz_override_beats_global(): ...      # resolve(key, quiz) == override, resolve(key, other) == global
def test_deleting_override_returns_to_global(): ...
def test_unknown_key_is_refused(): ...          # pytest.raises(UnknownSetting)
def test_invalid_value_is_refused(): ...        # pytest.raises(InvalidSettingValue), no row stored
def test_change_is_audited(): ...               # AuditEvent action "setting.changed", details key and value
```

`tests/api/test_admin_settings.py`: `test_settings_page_requires_login`; `test_global_setting_is_saved_and_shown`; `test_invalid_posted_value_shows_form_error_and_stores_nothing`; `test_quiz_override_form_saves_and_clears`; `test_quiz_override_does_not_create_a_draft` (published quiz, post the override, `QuizRevision` DRAFT count is 0).

- [x] **Step 2: Run to verify failure**

Run: `d uv run pytest tests/domain/test_settings.py tests/api/test_admin_settings.py -q`
Expected: FAIL, `app.domain.settings` missing.

- [x] **Step 3: Implement**

Routes: `GET/POST /admin/settings` (name `admin_settings`) and `POST /admin/quizzes/<uuid:quiz_id>/settings` (name `admin_quiz_settings`). The override is a form of its own on the edit page, not a field of `QuizForm`, so it never touches the draft. Its empty choice reads "Use global setting (now: X)". Add a nav link. Settings use the same `_()` catalogue as other admin strings; `d make messages`.

- [x] **Step 4: Run to verify passing**

Run: `d uv run pytest tests/domain/test_settings.py tests/api/test_admin_settings.py tests/test_translations.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add docs/superpowers/specs docs/superpowers/plans app tests
git commit -m "feat: add global settings with per-quiz override"
```

### Task 2: Contract: describing a definition, showing a given answer

**Files:**
- Modify: `app/contracts/__init__.py`, `app/plugins/questions/choice_single/plugin.py`, `app/plugins/questions/choice_single/jinja2/choice_single/public.html`, `tests/contracts/question_type.py`, `tests/contracts/test_choice_single.py`, `tests/fixtures/demo_site/kvz_demo_question/question.py`, `tests/kernel/test_registry.py`, `docs/_architecture/modules/contracts.md`, `docs/plugin-api.md`

**Interfaces:**
- Produces, in `app.contracts`: frozen dataclass `DefinitionRow(key: str, label: str, locale: str | None, value: str)`. `key` is stable across revisions of the same question, for example `"prompt"`, `"option:aaaa1111"`, `"correct"`. `label` follows the active translation; `value` is plain text, never markup.
- `QuestionTypePlugin.describe_definition(config: JSON, locales: Sequence[str]) -> list[DefinitionRow]`.
- `QuestionTypePlugin.render_public(public_config: JSON, locale: str, answer: JSON | None = None) -> str`.
- No release exists, so `CONTRACT_VERSION` stays `1.0`.

- [x] **Step 1: Write failing contract tests.** New class attributes: `changed_definitions: list[dict]` (each differs from `definition` in one field, and together they cover every field) and `answer_marker: str` (what `render_public` must contain when given `valid_answer`, for choice.single `"checked"`). `payload()` is a small helper in the suite returning `public_payload(self.definition, self.locale)`.

```python
def test_describe_returns_plain_rows(self):
    rows = self.plugin.describe_definition(self.definition, self.locales)
    assert rows and all(isinstance(row, DefinitionRow) for row in rows)
    assert len({(row.key, row.locale) for row in rows}) == len(rows)

def test_any_definition_change_changes_the_description(self):
    original = self.plugin.describe_definition(self.definition, self.locales)
    for changed in self.changed_definitions:
        assert self.plugin.describe_definition(changed, self.locales) != original

def test_render_public_without_answer_marks_nothing(self):
    html = self.plugin.render_public({**self.payload(), "id": "q1"}, self.locale)
    assert self.answer_marker not in html

def test_render_public_shows_given_answer(self):
    html = self.plugin.render_public({**self.payload(), "id": "q1"}, self.locale, self.valid_answer)
    assert self.answer_marker in html
```

`test_choice_single.py`: `changed_definitions` changing the prompt, one option text and `correct`; `test_describe_marks_the_correct_option`; `test_describe_covers_each_locale`.

- [x] **Step 2: Run to verify failure**

Run: `d uv run pytest tests/contracts -q`
Expected: FAIL, `DefinitionRow` missing.

- [x] **Step 3: Implement in `app/contracts/__init__.py` and `plugin.py`.** choice.single rows: `prompt` per locale, `option:<id>` per locale, `correct` with locale `None` and the default locale's option text as its value. Update the two test doubles and both docs.

- [x] **Step 4: Run to verify passing**

Run: `d uv run pytest tests/contracts tests/kernel tests/integration -q`
Expected: PASS.

- [x] **Step 5: Commit**: `feat: let question types describe definitions and show a given answer`

### Task 3: Round follows a new revision

**Files:**
- Create: `app/domain/migrations/0003_runrevision_attempt_switched.py`, `tests/domain/test_run_revisions.py`
- Modify: `app/domain/models.py`, `app/domain/authoring.py`, `app/domain/usage.py`, `tests/domain/test_attempts.py`, `tests/domain/test_usage.py`, `tests/api/test_play.py`, `tests/api/test_public_pages.py`

**Interfaces:**
- Consumes: `settings.resolve`, `settings.Policy` (Task 1).
- Produces:
  - Model `RunRevision`, table `run_revision`: `run` (`related_name="revision_rows"`), `revision` (`PROTECT`), `active_from`, `active_to` nullable, `max_score`, `switch_mode` with `SwitchMode.FINISH="finish"`, `SwitchMode.SWITCH="switch"`.
  - `Attempt.Status.SWITCHED = "SWITCHED"`; `Attempt.replaced_by`, self FK, nullable, `PROTECT`.
  - In `authoring`: `Decision` with `NOTIFY_SWITCH="notify_switch"`, `LET_FINISH="let_finish"`, `STAY="stay"`; `RoundDecisionRequired(AuthoringError)`; `publish(quiz, *, admin_id, decision: str | None = None, expected_hash: str | None = None) -> QuizRevision` (`expected_hash` is used from Task 5); `round_outcome(quiz) -> str | None`: `None` with no open round, else the resolved policy.
  - `QuizRun.current_row() -> RunRevision`: the row with `active_to` null.
- Behaviour: with an open round, `publish` takes the mode from the resolved policy. A `decision` counts only when the policy is `ask`; there it is required, otherwise `RoundDecisionRequired` is raised before anything changes. `notify_switch` and `let_finish` close the current row (`active_to`), add a row for the new revision with `switch` or `finish`, and set `run.current_revision`. `stay` touches nothing about the round. `open_run` creates the first row with `finish`. The audit details of `quiz.published` gain `decision`.

- [x] **Step 1: Write failing tests** (`tests/domain/test_run_revisions.py`), all with an open round unless noted.

```python
def test_open_run_creates_first_row_with_finish(): ...
def test_let_finish_moves_new_attempts_to_new_revision(): ...       # new attempts.start → revision 2
def test_attempt_in_progress_stays_on_its_revision_after_let_finish(): ...  # submit scored by revision 1, AC-04
def test_notify_switch_records_switch_mode(): ...                   # run.current_row().switch_mode == "switch"
def test_stay_leaves_round_and_writes_no_row():
    ...
    assert run.current_revision_id == first.id and run.revision_rows.count() == 1
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert authoring.open_run(quiz, admin_id=ADMIN_ID).current_revision_id == second.id

def test_stay_keeps_earlier_switch_decision(): ...     # notify_switch to rev 2, stay on rev 3: current row stays switch
def test_ask_without_decision_raises_and_changes_nothing(): ...  # draft stays DRAFT, round on revision 1
def test_stored_policy_applies_without_decision(): ...  # override let_finish, publish without decision
def test_decision_is_ignored_when_policy_is_stored(): ...
def test_no_open_round_needs_no_decision(): ...
def test_decision_is_audited(): ...
def test_usage_counts_older_revisions_of_open_round(): ...  # revision 1 uses a type, revision 2 does not: disable refused
def test_data_migration_creates_rows_for_existing_rounds(): ...  # call the migration function on a round with no rows
```

- [x] **Step 2: Run to verify failure**

Run: `d uv run pytest tests/domain/test_run_revisions.py -q`
Expected: FAIL.

- [x] **Step 3: Implement.** The migration creates the table, adds the attempt fields and, by `RunPython`, adds a `finish` row per existing round, with `active_from=opened_at`. `max_score` is copied from the revision. Publication and the switch of the round stay in one `transaction.atomic()`. `usage._open_questions` iterates over every revision of the round's rows. Existing tests that publish during an open round pass `decision="let_finish"`, which is the old test's intent spelled out; they keep every assertion.

- [x] **Step 4: Run to verify passing**

Run: `d uv run pytest tests/domain tests/api/test_play.py tests/api/test_public_pages.py -q`
Expected: PASS.

- [x] **Step 5: Commit**: `feat: let an open round follow a new revision`

### Task 4: Participant switches to the new revision

**Files:**
- Create: `app/api/jinja2/public/_switch_notice.html`, `tests/domain/test_switch.py`, `tests/api/test_switch.py`
- Modify: `app/domain/attempts.py`, `app/api/play.py`, `app/api/rendering.py`, `app/urls.py`, `app/api/jinja2/public/_questions.html`, `app/plugins/theme_default/assets` stylesheet if the mark needs a style

**Interfaces:**
- Consumes: `RunRevision`, `Attempt.Status.SWITCHED`, `Attempt.replaced_by`, `QuizRun.current_row()` (Task 3); `render_public(..., answer)` (Task 2).
- Produces, in `app.domain.attempts`:
  - `must_switch(attempt: Attempt) -> bool`: true for `SWITCHED`; for `IN_PROGRESS` in an open round, true when `attempt.revision_id != run.current_revision_id` and `run.current_row().switch_mode == "switch"`.
  - `SwitchedAttempt` frozen dataclass: `started: StartedAttempt`, `answers: dict[str, JSON]`, `changed: set[str]` (ids of questions marked as changed).
  - `switch(attempt_id: UUID, token: str, answers: Mapping[str, JSON]) -> SwitchedAttempt`.
  - New error code `attempt_switched`: status 409, message "This attempt was replaced by a newer version of the quiz. Please reload the page." `submit` raises it for a `SWITCHED` attempt.
- `question_html(question, locale, answer=None, changed=False) -> Markup` wraps a changed question with a mark "This question changed".

- [x] **Step 1: Write failing domain tests** (`tests/domain/test_switch.py`)

```python
def test_switch_creates_attempt_on_current_revision(): ...
def test_old_attempt_is_switched_and_cannot_be_submitted(): ...  # AttemptError code attempt_switched
def test_new_attempt_inherits_start_and_expiry():
    assert new.started_at == old.started_at
    assert tokens.verify(result.started.token).expires_at == old.started_at + ATTEMPT_LIFETIME

def test_answer_to_unchanged_question_is_kept_and_changed_one_dropped(): ...
def test_answer_kept_when_only_points_differ(): ...
def test_answer_failing_new_validation_is_dropped(): ...
def test_new_and_removed_questions(): ...       # new id is empty and not in changed, removed id is gone
def test_double_request_creates_one_attempt(): ...      # Attempt count, same replacement id, different token
def test_chain_is_followed_to_its_end(): ...    # a1→a2→a3: switching a1 returns a3
def test_chain_ending_in_submitted_is_already_submitted(): ...
def test_invalid_token_is_refused(): ...
def test_token_of_other_attempt_is_refused(): ...
def test_closed_round_is_refused(): ...         # run_closed
def test_expired_attempt_is_refused(): ...      # attempt_expired
def test_same_revision_changes_nothing(): ...   # round already on the attempt's revision: same attempt, no new row
def test_switched_attempt_counts_in_no_result(): ...    # score stays None, status SWITCHED
```

`must_switch`: `test_let_finish_does_not_ask`, `test_notify_switch_asks`, `test_last_decision_wins`, `test_stay_after_switch_still_asks`, `test_switched_attempt_always_asks`, `test_submitted_attempt_does_not_ask`.

- [x] **Step 2: Write failing API tests** (`tests/api/test_switch.py`, using the `Play` helper from `test_play.py`)

```python
def test_questions_page_polls_every_30_seconds(client, run):
    assert 'hx-trigger="every 30s"' in Play(client, run).start_response.content.decode()

def test_status_is_204_when_nothing_changed(): ...
def test_status_returns_notice_and_switch_button_after_notify_switch():
    assert 'id="play-submit"' in html and 'hx-swap-oob="true"' in html and "/switch" in html

def test_status_stops_polling_when_round_closed(): ...       # 286
def test_status_stops_polling_for_unknown_attempt(): ...     # 286, no error page
def test_status_stops_polling_after_submission(): ...        # 286
def test_notice_is_translated(): ...                         # lang=uk
def test_switch_returns_questions_with_kept_answer_and_changed_mark(): ...
def test_switch_without_htmx_returns_whole_page(): ...
def test_old_tab_submit_after_switch_is_409_with_retarget(): ...
def test_switch_falls_back_when_language_was_removed(): ...  # new revision without uk, lang=uk: 200 in default language
def test_malformed_answers_are_dropped_not_refused(): ...    # a garbage value on switch: 200, that answer empty
def test_switch_page_has_no_answer_key(): ...
def test_flow_with_real_key_after_switch_submits_and_scores_on_new_revision(): ...
```

- [x] **Step 3: Run to verify failure**

Run: `d uv run pytest tests/domain/test_switch.py tests/api/test_switch.py -q`
Expected: FAIL.

- [x] **Step 4: Implement `switch`.** Verify as `submit` does, except that a `SWITCHED` attempt is allowed and followed along `replaced_by`. Everything from reading the attempt onward runs in one `transaction.atomic()` under `with_retry` (`IMMEDIATE` transactions serialise it). Create the attempt, then set `started_at` with `.update()`, because the field is `auto_now_add`. The token's `expires_at` comes from the original `started_at`. Answers on a repeated request come from that request's form.

- [x] **Step 5: Implement the views and markup.**

Routes: `GET /a/<uuid>/revision-status` (name `revision_status`), `POST /a/<uuid>/switch` (name `switch`, `csrf_exempt`, `require_POST`).

`revision_status` statuses: 204 nothing to do (`HTMX_CONFIG` already does not swap on it), 286 attempt missing, submitted or round closed, 200 with `_switch_notice.html`. The polling element in `_questions.html`:

```html
<div id="revision-notice" hx-get="{{ url('revision_status', args=[attempt.id]) }}?lang={{ locale }}"
     hx-trigger="every 30s" hx-swap="outerHTML"></div>
<button type="submit" id="play-submit">{{ _("Submit answers") }}</button>
```

The notice replaces the polling element, which stops polling, and carries an out-of-band `<button id="play-submit" hx-swap-oob="true" type="submit" formaction=".../switch" hx-post=".../switch" hx-target="#play">Switch</button>`. `switch` renders `_questions.html` through `_respond`, with the same `_answers()` parsing as submit; an unreadable form is `invalid_request`. The language comes from `_locale` against the new revision's locales, which falls back to its default. `d make messages`.

- [x] **Step 6: Run to verify passing**

Run: `d uv run pytest tests/domain tests/api/test_switch.py tests/api/test_play.py tests/test_translations.py tests/api/test_security_headers.py -q`
Expected: PASS.

- [x] **Step 7: Commit**: `feat: let participants switch to a new revision and keep unchanged answers`

### Task 5: Change overview and publication page

**Files:**
- Create: `app/domain/revision_diff.py`, `app/api/jinja2/admin/publish.html`, `app/api/jinja2/admin/_diff.html`, `tests/domain/test_revision_diff.py`
- Modify: `app/domain/authoring.py`, `app/api/admin_quizzes.py`, `app/api/jinja2/admin/quiz_edit.html`, `tests/api/test_admin_quizzes.py`, `tests/integration/test_ac01_question_plugin.py`, `tests/integration/test_vertical_slice.py`

**Interfaces:**
- Consumes: `describe_definition`, `DefinitionRow` (Task 2); `publish(..., decision, expected_hash)`, `round_outcome`, `RoundDecisionRequired` (Task 3).
- Produces:
  - `revision_diff.compare(old: JSON | None, new: JSON, locales: Sequence[str]) -> RevisionDiff`. `RevisionDiff` has `quiz_fields: list[FieldChange]` (title per locale, languages, default language), `added`, `removed`, `moved`, `changed: list[QuestionChange]` and `is_empty: bool`. `QuestionChange` has `number`, `label` and `rows: list[FieldChange]`; `FieldChange` has `label`, `locale`, `before: str | None`, `after: str | None`.
  - `authoring.future_snapshot(quiz) -> JSON`: title, default_locale, locales and questions as publication would store them; `_freeze` uses it too.
  - `authoring.snapshot_hash(quiz) -> str`: sha256 of its canonical JSON. Stale hash: `publish` raises `StalePublication(AuthoringError)`.
  - `authoring.latest_published(quiz) -> QuizRevision | None` (public rename of `_latest_published`).
- Points, scoring and type version are compared as rows in `QuestionChange` with translated labels. A type that is not installed falls back to one row whose value is the type id.
- `expected_hash=None` in `publish` skips the check, for services and tests; the view always passes the form's value, an empty string when it is missing.

- [x] **Step 1: Write failing tests.** `tests/domain/test_revision_diff.py`:

```python
def test_first_publication_shows_everything_as_added(): ...
def test_changed_correct_answer_is_listed(): ...     # row key correct, before and after
def test_added_removed_moved(): ...
def test_changed_points_and_scoring_are_listed(): ...
def test_title_and_language_changes_are_listed(): ...
def test_equal_snapshots_are_empty(): ...
def test_unavailable_type_does_not_break_comparison(): ...
```

`tests/domain/test_authoring.py` additions: `test_stale_hash_is_refused_and_nothing_published`; `test_title_change_changes_hash`; `test_question_change_changes_hash`.

`tests/api/test_admin_quizzes.py` additions: `test_publish_page_shows_changes`, `test_publish_page_lists_problems_and_offers_no_button`, `test_publish_page_offers_three_choices_with_let_finish_preselected_when_policy_is_ask`, `test_publish_page_states_outcome_for_stored_policy`, `test_publish_page_offers_nothing_without_open_round`, `test_post_with_stale_hash_shows_page_and_publishes_nothing`, `test_post_without_decision_under_ask_shows_page_with_message`, `test_overview_escapes_markup` (title and prompt `<script>x`), `test_overview_renders_with_uninstalled_type`, `test_edit_page_links_to_publish_page`.

- [x] **Step 2: Run to verify failure**

Run: `d uv run pytest tests/domain/test_revision_diff.py tests/domain/test_authoring.py tests/api/test_admin_quizzes.py -q`
Expected: FAIL.

- [x] **Step 3: Implement.** `quiz_publish` handles `GET` (page) and `POST`. The edit page gets a link in place of the publish form and loses the note "A round stays on the revision it was opened with". A successful publish redirects to the edit page. Move `_problem_text` use to the new page. `d make messages`.

- [x] **Step 4: Update the POST callers.** `test_ac01_question_plugin.py` and `test_vertical_slice.py` load the page and post its hash; every assertion stays. `deploy/smoke.sh` calls the service directly, so it needs no change.

- [x] **Step 5: Run to verify passing**

Run: `d uv run pytest tests/domain tests/api/test_admin_quizzes.py tests/integration tests/test_translations.py -q`
Expected: PASS.

- [x] **Step 6: Commit**: `feat: show changes and the round outcome before publication`

### Task 6: Revision history, return and discard

**Files:**
- Create: `app/api/admin_revisions.py`, `app/api/jinja2/admin/revisions.html`, `app/api/jinja2/admin/revision_compare.html`, `app/api/jinja2/admin/confirm.html`, `tests/api/test_admin_revisions.py`
- Modify: `app/domain/authoring.py`, `app/api/admin_urls.py`, `app/api/jinja2/admin/quiz_edit.html`, `tests/domain/test_authoring.py`

**Interfaces:**
- Consumes: `revision_diff.compare`, `_diff.html`, `latest_published` (Task 5).
- Produces, in `authoring`: `use_as_draft(quiz, revision, *, admin_id) -> QuizRevision`; `discard_draft(quiz, *, admin_id) -> None`, raising `NothingToDiscard(AuthoringError)` with no draft and `NeverPublished(AuthoringError)` with none published. Audit actions `quiz.revision_restored` (with `revision_no`) and `quiz.draft_discarded`.
- Routes under `/admin/quizzes/<uuid:quiz_id>/`: `revisions` (`admin_revisions`), `revisions/<int:revision_no>/compare` (`admin_revision_compare`, against the previous number; the first revision shows everything as added), `revisions/<int:revision_no>/restore` (`admin_revision_restore`, `GET` confirms only if a draft exists, `POST` acts), `draft/discard` (`admin_draft_discard`, `GET` confirms, `POST` acts). A draft cannot be restored from: 404.

- [x] **Step 1: Write failing tests.** Domain:

```python
def test_use_as_draft_copies_questions_and_quiz_fields(): ...   # title, locales, default back from the snapshot
def test_use_as_draft_leaves_old_revision_identical(): ...      # checksum and snapshot_json unchanged
def test_use_as_draft_publishes_under_a_new_number(): ...
def test_use_as_draft_keeps_question_ids(): ...
def test_use_as_draft_replaces_existing_draft(): ...            # still one DRAFT
def test_discard_restores_fields_and_removes_draft(): ...       # title edit undone, DRAFT count 0
def test_discard_never_published_is_refused(): ...
def test_discard_without_draft_is_refused(): ...
def test_both_are_audited(): ...
def test_returned_revision_with_uninstalled_type_is_a_publication_problem(): ...
```

API: `test_revisions_page_requires_login`, `test_revisions_page_lists_numbers_statuses_and_scores`, `test_revisions_page_lists_historical_rounds_with_revisions_and_submitted_count`, `test_compare_shows_differences`, `test_compare_of_first_revision_shows_all_added`, `test_restore_without_draft_acts_without_confirmation_page`, `test_restore_with_draft_asks_first`, `test_get_on_restore_changes_nothing`, `test_discard_asks_first`, `test_discard_refusal_is_explained_on_never_published_quiz`, `test_compare_unknown_number_is_404`, `test_restore_of_other_quizs_revision_is_404`.

- [x] **Step 2: Run to verify failure**

Run: `d uv run pytest tests/domain/test_authoring.py tests/api/test_admin_revisions.py -q`
Expected: FAIL.

- [x] **Step 3: Implement.** Restoring and discarding write the quiz row and the draft in one transaction. Number of submitted attempts per round is one aggregated query, not one per round. `d make messages`.

- [x] **Step 4: Run to verify passing**

Run: `d uv run pytest tests/domain tests/api/test_admin_revisions.py tests/test_translations.py -q`
Expected: PASS.

- [x] **Step 5: Commit**: `feat: add revision history, return to an older revision and draft discard`

### Task 7: Duplicate, archive and restore a quiz

**Files:**
- Create: `app/domain/migrations/0004_quiz_archived_at.py`, `tests/domain/test_quiz_management.py`, `tests/api/test_admin_quiz_management.py`
- Modify: `app/domain/models.py`, `app/domain/authoring.py`, `app/api/admin_quizzes.py`, `app/api/admin_revisions.py`, `app/api/admin_urls.py`, `app/api/public.py`, `app/api/jinja2/admin/quiz_list.html`, `app/api/jinja2/admin/quiz_edit.html`

**Interfaces:**
- Consumes: `use_as_draft`, `discard_draft` (Task 6), `publish` (Task 3), `latest_published` (Task 5).
- Produces: `Quiz.archived_at`; in `authoring`: `duplicate_quiz(quiz, slug: str, *, admin_id) -> Quiz`; `archive_quiz(quiz, *, admin_id)`, raising `RunStillOpen(AuthoringError)`; `restore_quiz(quiz, *, admin_id)`; `QuizArchived(AuthoringError)`, raised by every editing service.
- Routes: `quizzes/<id>/duplicate` (`admin_quiz_duplicate`, `GET` form with slug `<slug>-kopie`, deduplicated with a number), `quizzes/<id>/archive` (`admin_quiz_archive`, `POST`), `quizzes/<id>/restore` (`admin_quiz_restore`, `POST`). Admin list: `?archived=1` shows archived quizzes only.

- [x] **Step 1: Write failing tests.** Domain:

```python
def test_duplicate_copies_title_languages_and_questions_as_draft(): ...
def test_duplicate_has_no_revisions_rounds_or_attempts_and_featured_off(): ...
def test_duplicate_of_archived_copies_draft_else_highest_archived(): ...
def test_duplicate_with_taken_slug_is_refused(): ...
def test_archive_with_open_round_is_refused(): ...
def test_archive_turns_published_into_archived(): ...
def test_archive_keeps_draft_untouched(): ...
def test_archived_quiz_refuses_editing_publishing_opening_return_and_discard(): ...  # parametrize each service, QuizArchived
def test_restore_returns_highest_archived_to_published(): ...
def test_restore_makes_draft_editable_again(): ...
def test_archive_of_never_published_quiz_works(): ...
def test_archive_and_restore_do_not_change_revision_content(): ...   # checksum and snapshot_json
def test_both_are_audited(): ...
```

API: `test_archived_quiz_has_no_public_page`, `test_archived_quiz_url_with_run_has_no_public_page`, `test_archived_quiz_is_hidden_from_default_list_and_shown_by_filter`, `test_archive_refusal_is_explained_on_edit_page`, `test_edit_page_of_archived_quiz_is_read_only_with_restore`, `test_post_to_question_edit_of_archived_quiz_is_409`, `test_duplicate_form_prefills_free_slug`, `test_duplicate_redirects_to_new_quiz_editor`, `test_restored_quiz_can_publish_and_open_round`.

- [x] **Step 2: Run to verify failure**

Run: `d uv run pytest tests/domain/test_quiz_management.py tests/api/test_admin_quiz_management.py -q`
Expected: FAIL.

- [x] **Step 3: Implement.** Status changes use `.filter().update()`, because `QuizRevision.save` refuses non-drafts. `get_draft`, `save_question`, `delete_question`, `publish`, `open_run`, `use_as_draft` and `discard_draft` check `archived_at` first. Views turn `QuizArchived` into the edit page with status 409 and a message. `public.quiz` and `public.quiz_run` return `_unavailable` for an archived quiz. Duplicate reuses `IntegrityError` handling from `admin_users.py` for a slug race. `d make messages`.

- [x] **Step 4: Run to verify passing**

Run: `d uv run pytest tests/domain tests/api tests/test_translations.py -q`
Expected: PASS.

- [x] **Step 5: Commit**: `feat: add quiz duplication, archive and restore`

### Task 8: Documentation and end-to-end proof

**Files:**
- Create: `docs/_architecture/adr/0038-revision-switch-policy-and-settings.md`, `tests/integration/test_revision_switch.py`
- Modify: `docs/_architecture/roadmap.md`, `README.md` in `docs/_architecture/` (FR map, identifier range, ADR index), `docs/_architecture/modules/domain.md`, `docs/_architecture/modules/api-ui.md`, `docs/_architecture/data-model.md`, `docs/_architecture/acceptance-criteria.md`, `docs/_architecture/adr/README.md`, `CLAUDE.md`, `README.md`, `deploy/smoke.sh`

**Interfaces:**
- Consumes: everything above.

- [x] **Step 1: Write the failing end-to-end test** `tests/integration/test_revision_switch.py::test_switch_flow_end_to_end`, through HTTP only: an admin sets the policy to `notify_switch`, two participants start, an admin changes one of two questions and publishes via the page, the status response asks to switch, one participant switches and submits (unchanged answer kept, score from revision 2), the other submits the old attempt without switching (scored on revision 1), a new participant starts on revision 2.

- [x] **Step 2: Run it**

Run: `d uv run pytest tests/integration/test_revision_switch.py -q`
Expected: PASS, because the feature exists. A failure is a defect in Tasks 3 to 5: fix it there with its own failing test.

- [x] **Step 3: Extend `deploy/smoke.sh`:** after the existing flow, publish a second revision with `decision="let_finish"` and check that `/q/<slug>` still answers 200 and that a new start answers 200.

- [x] **Step 4: Update the docs.**

- `roadmap.md`: B1 row gains the status "Done" with the date, and the content of B1, B2 and B3 gains the stage additions from the spec's table.
- `domain.md`: define `FR-47` (revision switch policy and its three values, `stay`, switching and moved answers), `FR-48` (change overview before publication), `FR-49` (return to an older revision, discard). Update the run lifecycle and `FR-09` text.
- `api-ui.md`: define `FR-50` (global settings with per-quiz override); add the new routes; replace the sentence about a run staying on its revision if present.
- `data-model.md`: `app_setting`, `run_revision.switch_mode`, `attempt.status` `SWITCHED`, `attempt.replaced_by`.
- `acceptance-criteria.md`: `AC-19` (switch), `AC-20` (override), `AC-21` (overview), `AC-22` (return and archive), values from the spec's Acceptance section.
- `docs/_architecture/README.md`: `FR-01`…`FR-50`, map entries for FR-47 to FR-50, and the note on later additions.
- ADR-0038 (MADR 4, status accepted, date 2026-11-06): options considered are always ask, fixed behaviour, and policy with global default and quiz override; record the `stay` rule and the page-rule limit.
- `CLAUDE.md`, root `README.md`: state that B1 is done and B2 is next.

- [x] **Step 5: Verify the whole stack**

Run: `d make quality; echo $?` and `make smoke; echo $?`
Expected: both `0`, `SMOKE OK`.

- [x] **Step 6: Browser walkthrough** with Playwright against an isolated Docker stack on port 18443 (context with `ignoreHTTPSErrors`): round open, participant on a phone-width viewport (390 px) in one tab; publish a change with `notify_switch` in another. Expect the notice within 30 s, "Switch" in place of the submit button, a kept answer, a marked changed question, and no CSP errors in the console. Also view the publish page and revision list at 390 px with no horizontal overflow.

- [x] **Step 7: Commit**: `docs: record revisions, switch policy and settings; extend smoke test`

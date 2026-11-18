# C3 Data policies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A run stores only what its data profile allows (nothing, score, answers, detailed), records a retention period, and a participant can resume an unsubmitted attempt in the same browser.

**Architecture:** The domain catalogue (`app/domain/settings.py`) replaces `store_answers` with `data_profile` and adds `retention_period`; a new `app/domain/data_policy.py` owns the run snapshot (`QuizRun.retention_json`), the conflicts of `none`, and the stateless count. `attempts.py` freezes the profile at start, stores rows and duration by it, and deletes a stateless attempt in the submit transaction. Local resume is a `quiz_flow` setting, a POST route that re-renders an attempt from its token, and a script `resume.js` that keeps a copy in `localStorage`.

**Tech Stack:** Python 3.15, Django 6.1, Jinja2, HTMX, SQLite WAL, plain JS (no build), pytest.

**Spec:** `docs/superpowers/specs/2026-11-08-c3-data-policies-design.md`

## Global Constraints

- Branch `feat/c3-data-policies` from `main`. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `make` needs uv 0.13+: `export PATH=<uv-0.13>/bin:$PATH`.
- Settings follow `kvizotron-add-setting`: scopes `("global", "quiz")` with a written reason (the whole attempt or run, ADR-0042).
- `data_profile` values `none`, `score`, `answers`, `detailed`; default `score`. Upgrade map: `store_answers=all` → `answers`, `images` → `score`.
- `retention_period` values `30d`, `90d`, `180d`, `1y`, `3y`, `permanent`; default `90d`.
- `local_resume` values `on`, `off`; default `on`.
- Browser copy expiry: the attempt's end when it has one, else start + 24 h, never more than 24 h.
- No name, e-mail, answer or token in a log, an audit `details`, a URL or `localStorage` beyond what the spec lists (token, answers without photos and identity fields, step, expiry).
- Every text in cs, en, uk via `make messages`; a run is `běh` / `run`, never `kolo`.
- Phone width, light and dark, keyboard; no build step; scripts are files in `app/api/assets/` (CSP forbids inline).
- New ADR is 0050, new AC from AC-77; each new AC is named by a test (`tests/test_docs.py`). Tests for AC-09 and AC-11 name them too.

## Review Focus

1. Automatic and manual stateless submissions racing: one counts once, the other sees "already submitted or ended", the count is 1. Tested in Task 3.
2. An attempt started before the upgrade, submitted after it: its frozen `store_answers` still decides what is stored. Tested in Task 2.
3. A stateless attempt that was switched to a new revision: the whole `replaced_by` chain goes, not only the last row. Tested in Task 3.
4. A browser copy from another run, or one whose attempt was submitted in another tab: "Continue" is refused and the copy deleted, no new attempt starts. Tested in Task 4.
5. A stored answer that no longer fits after a revision switch (an option removed): dropped silently, the page still loads. Tested in Task 4 (browser step in Task 5).

---

### Task 1: Profile and period as settings, run snapshot, admin forms

**Files:**
- Modify: `app/domain/settings.py` (drop `STORE_ANSWERS`/`StoreAnswers`; add `DATA_PROFILE`, `DataProfile`, `RETENTION_PERIOD`, `RetentionPeriod`; `is_visibility_conflict(profile, visibility)`)
- Create: `app/domain/data_policy.py`
- Modify: `app/domain/models.py` (`QuizRun.retention_json` JSONField default dict, `QuizRun.stateless_submitted` PositiveIntegerField default 0); Create: `app/domain/migrations/0013_data_policies.py`
- Modify: `app/domain/authoring.py` (`open_run`), `app/domain/run_schedule.py` (`plan`, `update_plan`, new `set_period`), `app/api/admin_forms.py` (`_refuse_visibility_conflict`, `RunPlanForm`), `app/api/admin_runs.py`, `app/api/admin_urls.py`, `admin/run_plan.html`, `admin/run.html`
- Modify tests that set `store_answers`: `tests/domain/test_stored_answers.py`, `tests/domain/test_visibility.py`, `tests/api/test_stored_answers.py`, `tests/api/test_walkthrough.py`, `tests/api/test_grading.py`, `tests/api/test_result_link.py`, `tests/api/test_run_archive.py` (`store_answers=all` → `data_profile=answers`; no assertion weakened)
- Test: `tests/domain/test_data_policy.py`, `tests/api/test_run_plan.py`, `tests/domain/test_migration_0013.py`

**Interfaces:**
- `data_policy.rules_for_quiz(quiz: Quiz) -> dict[str, str]` → `{"profile": ..., "period": ...}` resolved for the quiz.
- `data_policy.snapshot(quiz: Quiz, chosen: Mapping[str, str] | None) -> dict[str, str]` (same shape as `participants.snapshot`).
- `data_policy.of(run: QuizRun) -> dict[str, str]`: normal run → its `retention_json` filled with defaults; test run → `rules_for_quiz(run.quiz)`.
- `data_policy.profile_of_attempt(attempt: Attempt) -> str`: `settings_json["profile"]`, else the upgrade map of `settings_json["store_answers"]`, else `score`.
- `data_policy.keeps_all_answers(profile: str) -> bool` (`answers`, `detailed`); `keeps_duration(profile: str) -> bool` (`detailed`).
- `open_run`, `plan`, `update_plan` take `data: Mapping[str, str] | None = None`; the profile never changes once `OPEN`.
- `run_schedule.set_period(run: QuizRun, period: str, *, admin_id: str) -> None`: any status but test; audit `run.period_changed` with `{"period": period}`. Route POST `admin/runs/<id>/period` name `admin_run_period`.
- `RunPlanForm` gets `data_profile` and `retention_period` `ChoiceField`s, initial from `rules_for_quiz`, method `data() -> dict[str, str]`. Each profile value has a help line: what it keeps, and for `none` what it rules out (attempts table, result link, later scoreboard, draw, export); `score` says rankings by time need `detailed`.
- Migration 0013: adds the two fields; renames every `AppSetting` row `store_answers` to `data_profile` with the upgrade map; sets each existing normal run's `retention_json` to `{"profile": <quiz override, else global row, else score>, "period": "90d"}`.

- [ ] **Step 1: Tests** (`AC-77`, `AC-79` in module docstrings): `test_open_copies_profile_and_period`; `test_quiz_change_after_open_does_not_touch_run`; `test_plan_form_sets_profile_and_period`; `test_open_run_profile_fixed` (`update_plan` on `OPEN` refused as today); `test_period_editable_on_open_and_ended_run` (POST `admin_run_period`, value stored, audit row without other data); `test_period_refused_on_test_run`; `test_visibility_needs_answers_profile` (quiz form with `answers_visibility=participant` and `data_profile=score` refused, with `answers` accepted); `test_run_page_shows_profile_and_period`; `test_migration_maps_store_answers` (`MigrationExecutor` from 0012 to 0013: global `all` → `answers`, quiz override `images` → `score`, an open run gets its quiz's mapped value and `90d`).
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_data_policy.py tests/api/test_run_plan.py tests/domain/test_migration_0013.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces; `make messages` for new strings.
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(data): data profile and retention period on the run`.

### Task 2: Store by profile

**Files:**
- Modify: `app/domain/attempts.py` (`_begin_attempt` freezes `"profile": data_policy.of(run)["profile"]` instead of `store_answers`; `_row` and `_score` use `profile_of_attempt`; `_store` writes `duration_ms` only when `keeps_duration`), `app/domain/models.py` (docstring of `AttemptAnswer`), `app/api/admin_links.py` (duration column blank when `None`, already so; keep)
- Test: `tests/domain/test_profile_storage.py`

**Interfaces:**
- Consumes Task 1 `data_policy.of`, `profile_of_attempt`, `keeps_all_answers`, `keeps_duration`.

- [ ] **Step 1: Tests** (`AC-77`): `test_score_keeps_score_and_time_only` (no `AttemptAnswer` for a choice question, `duration_ms is None`, `score` and `submitted_at` set); `test_score_keeps_answers_needing_a_person` (photo or manual text question has its row); `test_answers_keeps_every_answered_question_without_duration`; `test_detailed_keeps_answers_and_duration`; `test_attempt_started_before_upgrade_keeps_its_frozen_store_answers` (attempt with `settings_json={"store_answers": "all", ...}` submitted → rows stored, no duration); `test_test_link_follows_quiz_profile`.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_profile_storage.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(data): store attempts by their profile`.

### Task 3: Stateless mode

**Files:**
- Modify: `app/domain/data_policy.py` (conflicts), `app/domain/attempts.py` (`submit`, `_store`, `_load` callers), `app/domain/authoring.py` (`open_run`, `publish`: `_round_decision` and the scheduled-run update), `app/domain/run_schedule.py` (`plan`, `update_plan`, opening a planned run in `settle`), `app/api/play.py` (`STATUS`, result without link), `app/api/admin_forms.py` (quiz and global settings forms, plan form), `app/api/admin_runs.py` and `admin/run.html` (count instead of the table), `public/quiz.html` (one line before the start under `none`), `public/_result.html`
- Test: `tests/domain/test_stateless.py`, `tests/api/test_stateless_flow.py`

**Interfaces:**
- `data_policy.conflicts(profile: str, rules: Mapping[str, str], visibility: str, snapshot: Mapping[str, Any] | None) -> list[str]`: for `none` the keys in conflict, from `repeat_attempts` (forbid), `ask_name`, `ask_email` (not `off`), `answers_visibility` (not `admins`), and `"photo_question"` when the snapshot has a question with `file_fields`. Empty for other profiles.
- `data_policy.StatelessConflict(Exception)` with `keys: list[str]`; raised by `open_run`, `plan`, `update_plan` and the planned-run opening in `settle` (that one leaves the run planned and records audit `run.open_refused` with the keys). Forms catch it and show one message per key naming the setting.
- Quiz and global settings forms refuse `none` with conflicting setting values (snapshot `None` there).
- `publish`: when the open run's profile is `none` and the new revision has a photo question, the round decision becomes `stay`; scheduled `none` runs keep their revision likewise. `publish` returns as today; the publish page shows a notice "The running stateless run keeps its revision: the new one has a photo question." (`PublishResult` or a flag the view reads; builder's choice).
- In `_store`, profile `none`: in the same transaction, after the score is computed, delete the attempt and every attempt reaching it through `replaced_by` (oldest first), increment `QuizRun.stateless_submitted` with `F() + 1`, emit `attempt.submitted` with `run_id`, score and max only. No `AttemptAnswer` exists to delete (rows are not built under `none`).
- `submit`, `check`, `attempt_time`, `switch`, `revision_status` with a valid token whose row is gone, on a `none` run: `AttemptError("attempt_gone")` → 410, message "This attempt has already been submitted or has ended." (cs "Tento pokus už byl odeslán nebo skončil.") No tombstone row.
- Result under `none`: score shown, no private link, one line saying it cannot be shown again.
- Quiz page under `none`: "The result is shown only once after you submit, and it is not saved anywhere."
- Run page under `none`: "Attempts submitted: N" instead of the attempts table.

- [ ] **Step 1: Tests** (`AC-09`, `AC-78`): `test_stateless_submit_leaves_no_rows` (after submit: no `Attempt`, `AttemptAnswer`, `Participant` for the run; response shows the score; count 1); `test_stateless_result_has_no_link`; `test_repeated_stateless_submit_is_gone_410` (second POST same token and key → 410 with the message, count still 1); `test_racing_auto_and_manual_stateless_submit_counts_once` (`transaction=True`, two threads, helper `waiting()`); `test_switched_stateless_attempt_deletes_chain`; `test_unsubmitted_stateless_attempt_stays_anonymous`; `test_open_refuses_none_with_forbid_name_email_visibility_photo` (parametrised, each key named); `test_quiz_settings_form_refuses_none_with_ask_name`; `test_planned_none_run_with_photo_revision_does_not_open` (stays planned, audit row); `test_publish_keeps_revision_of_running_none_run_with_photo`; `test_run_page_shows_count_not_table`; `test_quiz_page_warns_score_shown_once`.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_stateless.py tests/api/test_stateless_flow.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(data): stateless mode`.

### Task 4: Local resume, server side

**Files:**
- Modify: `app/plugins/quiz_flow/manifest.py` (setting `local_resume`), `app/contracts/__init__.py` (`LOCAL_RESUME = "local_resume"` key constant, if the other flow keys live there; else the plugin)
- Modify: `app/domain/attempts.py` (new `resume_by_token`), `app/api/play.py` (new view `resume`), `app/urls.py`
- Modify: `public/_questions.html` (data attributes the script reads: run id, expiry ISO, `local_resume` flag, photo note text), `public/quiz.html` (hidden "Continue"/"Start again" block, shown by the script)
- Test: `tests/domain/test_local_resume.py`, `tests/api/test_local_resume.py`

**Interfaces:**
- Manifest setting: `{"key": "local_resume", "choices": ["on", "off"], "default": "on", "scopes": ["global", "quiz"], "scope_reason": "Applies to the whole attempt, not to one question.", "label": "Resume in this browser", "value_labels": {"on": ..., "off": ...}, "help": "Answers stay on this device until the attempt ends, at most 24 hours; a shared device can show them to the next person."}`. Frozen on the attempt at start as `settings_json["local_resume"]`.
- `attempts.copy_expiry(attempt: Attempt) -> datetime`: `min(attempt end from limit and deadline if any, started_at + 24 h)`.
- `attempts.resume_by_token(run: QuizRun, attempt_id: UUID, token: str) -> StartedAttempt`: verifies the token and claims; follows `replaced_by` to the live attempt; refuses with `AttemptError`: `not_in_run` (other run), `attempt_closed` (abandoned), `already_submitted` (finished), `attempt_gone` (row missing under `none`), `run_closed`/time codes as `_check_still_valid` does, `resume_off` (frozen flag off). Needs no access-code cookie. Returns `resume(attempt)`.
- View `play.resume`: POST `r/<run_id>/resume` name `resume`, fields `attempt_id`, `attempt_token`; renders `public/_questions.html` exactly as `start` does, plus `resume=True` in the context. Refusals use the existing message fragment with header `X-Kvz-Drop-Copy: 1`, which tells the script to delete the copy. CSRF as `start`.
- The template marks the attempt as resumable only when `settings_json["local_resume"] == "on"`.

- [ ] **Step 1: Tests** (`AC-11`, `AC-80`): `test_resume_returns_same_attempt_questions_and_start`; `test_resume_needs_no_code_cookie`; `test_resume_refused_for_other_run`; `test_resume_refused_after_submit_and_drops_copy` (header present); `test_resume_refused_after_limit`; `test_resume_refused_when_abandoned`; `test_resume_follows_switch_chain`; `test_resume_off_refused`; `test_copy_expiry_takes_limit_deadline_or_24h` (three cases); `test_used_mode_allows_resume_of_same_attempt`; `test_token_never_in_url` (rendered HTML: the token appears only in hidden inputs and data attributes, never in an `href` or `action`).
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_local_resume.py tests/api/test_local_resume.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(flow): resume an attempt by its token`.

### Task 5: Local resume, browser side

**Files:**
- Create: `app/api/assets/resume.js`; Modify: the base public template that loads `flow.js`/`play.js` (load `resume.js` the same way), `tests/test_wiring.py` only if assets are listed there explicitly
- Modify: `public/quiz.html`, `public/_questions.html`, `app/plugins/theme_default/assets/theme.css` (spacing of the two buttons, phone width)
- Test: `tests/api/test_local_resume.py` (HTML hooks), browser check in Step 4

**Interfaces:**
- `localStorage` key `kvz-attempt-<run id>`; value JSON `{"attempt": id, "token": t, "expires": iso, "step": n, "answers": {name: value | [values]}}`. Answers are read from the form's inputs except `type=file`, `participant_name`, `participant_email`, `attempt_token`, `submission_key`, `csrfmiddlewaretoken`.
- Saved on `change` and on step moves (`flow.js` dispatches `kvz:step` with the index; add that event), only when the form says resumable. Deleted on `htmx:afterSwap` of a result, on a response with `X-Kvz-Drop-Copy`, and when expired at page load. Every access in `try/catch` (private mode).
- On the quiz page with a valid copy for the shown run: the block with "Continue" (primary) is shown; "Start again" stays only when the server rendered it (`data-may-restart`, true for `repeat_attempts=allow` or `unfinished_attempt=submitted`). "Continue" POSTs the token to `resume` by HTMX into the same target as start, then fills the answers (unknown names and values that match no input are skipped) and moves `flow.js` to the stored step (`kvz:goto` event handled by `flow.js`).
- After resuming, a photo question shows the note "Fotku vyberte znovu."
- With resume on, the form shows one line near the submit button: "Answers are kept in this browser until you submit, for 24 hours at most." (spec Risks: shared device).

- [ ] **Step 1: Tests**: `test_questions_carry_resume_hooks` (data attributes and the device line present when on, absent when `local_resume=off`); `test_quiz_page_has_hidden_continue_block`; `test_may_restart_follows_rules` (`allow` true, `used` false, `submitted` true).
- [ ] **Step 2: Run** them. Expected: FAIL. Implement. Run plus `make test`. Expected: PASS.
- [ ] **Step 3: Commit** `feat(flow): keep and restore answers in the browser`.
- [ ] **Step 4: Browser check** (skill `kvizotron-browser-walkthrough`, new quiz `c3-…`): reload mid-attempt in all-at-once and step mode restores answers and step; photo note shown; "Start again" shown under `allow`, hidden under `used`; copy gone after submit (`localStorage` read in the page); refused resume after submit in another tab deletes the copy. Fix what fails with a failing test first where HTML can show it.

### Task 6: Privacy page, translations, documents, final checks

**Files:**
- `app/api/jinja2/public/privacy.html` (or the info template it uses): the global default period, that a quiz may set another, that deletion arrives in a later version, that answers may stay in this browser until the attempt ends, at most 24 hours
- Locale catalogues via `make messages` (cs, en, uk for every new string)
- `docs/_architecture/adr/0050-data-profile-and-local-resume.md`, `adr/README.md`; ADR-0020 and ADR-0012 get "Refined by ADR-0050" in More Information
- `docs/_architecture/acceptance-criteria.md` (AC-77 profile storage, AC-78 stateless, AC-79 period, AC-80 resume, as named in the tests)
- `docs/privacy.md` (dependency table final, profile replaces `store_answers`, period without job until D3, browser copy), `docs/_architecture/adr/0046-…` unchanged but `data-model.md` (`retention_json` content, `stateless_submitted`), `modules/domain.md`, `modules/api-ui.md` (routes `resume`, `admin_run_period`; "Where things are set"), `plugins/quiz-flow.md`, `providers/retention.md` (C3 part done, job in D3), `roadmap.md` (C3 Done), `CLAUDE.md` (milestones, Status, "Next is C4"), touched `app/*/CLAUDE.md`, `.claude/skills/kvizotron-check-integration/flows.md` (profile → start → submit → stored or deleted; copy → resume → submit)

ADR-0050 records: one profile replacing `store_answers`, the four values and the upgrade map, the stateless attempt living until submission with no tombstone, the period as a run value without a job, local resume on by default (changes ADR-0020's opt-in), the token as proof for resume without the code cookie.

- [ ] **Step 1:** `make messages`, fill every empty `msgstr` in cs and uk, run `make messages` again.
- [ ] **Step 2:** Write the documents above.
- [ ] **Step 3: Run** `make quality`. Expected: PASS.
- [ ] **Step 4: Run** `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke`. Expected: PASS (migration 0013 on a clean build).
- [ ] **Step 5: Commit** `docs: C3 data policies`.
- [ ] **Step 6:** Verification by `kvizotron-milestone` step 3: walkthrough on a new quiz in `kvizotron-browser` (spec Verification list), `kvizotron-check-applied`, final review.

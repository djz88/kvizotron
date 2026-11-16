# Release review fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the confirmed defects, the usability gaps and the housekeeping found by the 2026-11-16 review, in the review's recommended order, so the remaining 1.0 release checks (`make load`, restore drill) run against fixed code.

**Architecture:** Five phases, each a reviewable unit: A fixes server-side defects (domain and API, every fix starts with a failing test); B fixes what a person meets first (duplicate "End the run", new quiz form, focus after start, empty submission); C decides TD-101/TD-036 through an ADR a human approves, then freezes flow and profile values on the run; D tidies the repository (`.mo` catalogs, untracked files, shared admin helpers, two oversized files); E runs the release checks from `docs/deployment.md`. The CI-on-GitHub item (TD-008) and the XFF smoke test are deliberately not in this plan.

**Tech Stack:** Django 5, Jinja2, HTMX, Pico CSS, pytest; `make lint`, `make test`, `make quality`, `make smoke`, `make load`.

**Spec:** `docs/superpowers/specs/2026-11-16-review-findings.md` (sections 3–6 are the source of every task; finding numbers below refer to section 3).

## Global Constraints

- Project rules in `CLAUDE.md`: features live in modules, not the kernel; `QuizRun` is "běh" in Czech UI, never "kolo"; every behaviour change has a test; tests are never weakened; secrets never enter code or logs.
- Settings inherit global → quiz → question (ADR-0042); a new setting needs the `kvizotron-add-setting` skill and a manifest `settings` entry.
- An ADR with status `proposed` is not decided: Phase C stops for a human before any code.
- Profile `kvizotron` for dev-workflow: `app/domain/models.py` + migrations, `app/api/play.py`, `app/domain/attempts.py` are VELKÁ/STŘEDNÍ; Phase C is VELKÁ.
- Translations: every new user-facing string goes through `_()` and `make messages` updates `cs` and `uk` catalogs (`.po` and `.mo` in git until Task D1 changes that).
- Commit after each task; `make quality` green before each commit.

## Review Focus

Inputs the spec implies but no task's tests exercise; each has a test pinned to the owning task:

1. Two admins start the same quiz within the same second (Task A1): exactly one run opens, the second sees "This quiz already has a running run." — test in Task A1.
2. A participant submits while the admin closes the run (Task B1): the submission gets the "run closed" refusal, not a 500 — test in Task B1.
3. A quiz name with only whitespace on the new quiz form (Task B2): the slug is not derived from it and the form shows the name error — test in Task B2.
4. A keyboard user tabs backwards right after start (Task B3): Shift+Tab from the focused heading lands on the skip link, not on the footer — covered by the walkthrough step in Task B3.
5. `make messages` on a clean tree (Task D1): leaves `git status` empty — test in Task D1.

---

## Phase A — server-side defects (findings 1–8, then 9–13)

### Task A1: Start from the publish page maps every open-run refusal

**Files:**
- Modify: `app/api/admin_quizzes.py:688-745` (`quiz_publish`, `run_open`)
- Test: `tests/api/test_admin_quizzes.py`

**Interfaces:**
- Produces: `_open_refusal(error: Exception) -> str | None` in `app/api/admin_quizzes.py`: the message for `authoring.NothingPublished`, `authoring.RunAlreadyOpen`, `authoring.RequirementUnmet`, `data_policy.StatelessConflict`, `results.ResultConflict`, `rewards.RewardConflict`; `None` for anything else.

- [ ] **Step 1: Write the failing tests**

```python
def test_start_from_publish_page_refuses_a_result_conflict(admin_client, quiz_with_result_conflict):
    response = admin_client.post(publish_url(quiz), {"start": "1", "snapshot_hash": current_hash(quiz)})
    assert response.status_code == 200  # the publish page again, not a 500
    assert result_messages(...)[0] in response.content.decode()

def test_start_from_publish_page_refuses_an_unmet_requirement(...)  # RequirementUnmet
def test_start_from_publish_page_refuses_a_reward_conflict(...)  # RewardConflict
def test_two_simultaneous_starts_open_one_run(admin_client, published_quiz):
    # two POSTs to run_open; one redirect to admin_run, one edit page with the already-open message; QuizRun count == 1
```

Build the conflicting quiz the way `tests/api/test_admin_runs.py` builds one for `run_plan` (`results.ResultConflict` comes from `run_results.ensure_run_allowed`).

- [ ] **Step 2: Run them, expect FAIL** — `uv run pytest tests/api/test_admin_quizzes.py -k "publish_page_refuses or simultaneous" -v` (500 or unhandled exception).

- [ ] **Step 3: Implement `_open_refusal` and use it in both views**

`quiz_publish`: wrap `publish_and_open` and `publish` in one `try`, add `except (results.ResultConflict, rewards.RewardConflict, authoring.RequirementUnmet) as error: return _publish_page(request, quiz, _open_refusal(error))`. `run_open`: replace its chain of `except` clauses with one `except Exception as error: message = _open_refusal(error); if message is None: raise; return edit_page(..., run_error=message)`. Message texts: reuse the ones already in `run_open` and `admin_runs.py:308-315` (`result_messages`, `conflict_messages`, `error.messages()`, `error.reasons`).

- [ ] **Step 4: Run the tests, expect PASS**; then `uv run pytest tests/api/test_admin_quizzes.py tests/api/test_admin_runs.py -q`.

- [ ] **Step 5: Commit** — `fix(admin): map every open-run refusal on the publish page`

### Task A2: Rate-limited public views take their slot atomically

**Files:**
- Modify: `app/api/play.py:194-203` (`_limited`), `app/api/play.py:444-470` (`enter_code`)
- Test: `tests/api/test_request_limits.py`

**Interfaces:**
- Consumes: `rate_limit.try_acquire(bucket, key, now) -> bool`, `rate_limit.release(bucket, key)` (`app/api/rate_limit.py:58-83`), as `admin_auth.py:55-68` uses them.

- [ ] **Step 1: Write the failing test**

```python
def test_concurrent_submits_from_one_address_never_exceed_the_limit(settings, run_with_attempts, monkeypatch):
    # KVZ_SUBMITS_PER_MINUTE = 5; 20 threads post /a/<id>/submit at a barrier (pattern: tests/api/test_login_limit.py:118)
    assert sum(r.status_code != 429 for r in responses) == 5

def test_a_wrong_code_counts_once_and_a_right_code_frees_its_slot(...):
    # KVZ_CODE_ATTEMPTS_PER_MINUTE = 2; wrong, wrong -> third wrong is 429; a right code after one wrong leaves one slot
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/api/test_request_limits.py -k "concurrent_submits or frees_its_slot" -v` (more than 5 pass through).

- [ ] **Step 3: Implement**

`_limited`: `if not rate_limit.try_acquire(bucket, ip, now): return 429 response`; return `None`. `enter_code`: `try_acquire("code", ip, now)` before the match; on a correct code `rate_limit.release("code", ip)` (only wrong guesses keep their slot, same rule as login). Drop the `allow()`/`record()` pairs.

- [ ] **Step 4: Run, expect PASS**; `uv run pytest tests/api/test_request_limits.py tests/api/test_access_code_flow.py -q`.

- [ ] **Step 5: Commit** — `fix(play): take rate-limit slots atomically on submit, start and code`

### Task A3: An archived quiz is read-only for grading, rewards, draws and run settings

**Files:**
- Modify: `app/domain/rewards.py:646` (`grant_manual`), `:693` (`hand_over`), `:704` (`cancel`); `app/domain/draws.py:135` (`_locked_run`); `app/domain/grading.py:83, 103, 125` (`save_manual`, `remove_photo`, `set_approved`); `app/domain/results.py:168` (`set_display`); `app/domain/participants.py:317` (`rename`); `app/domain/access_codes.py` (the function `admin_runs.run_code` calls)
- Modify: the views `admin_rewards.py:460, 486, 624`, `admin_grading.py:298, 321, 342`, `admin_runs.py:501, 617, 839` to answer `authoring.QuizArchived` with status 409 and the message the `not_archived` decorator uses (`admin_quizzes.py:262`)
- Test: `tests/domain/test_entitlements.py`, `tests/domain/test_grading.py`, `tests/domain/test_draws.py`, `tests/api/test_admin_rewards.py`

**Interfaces:**
- Consumes: `authoring.ensure_editable(quiz: Quiz) -> None` raises `authoring.QuizArchived` (`app/domain/authoring.py:143`).

- [ ] **Step 1: Write the failing tests** — one per entry point, same shape:

```python
def test_grant_manual_refuses_an_archived_quiz(archived_run, rule, participant):
    with pytest.raises(authoring.QuizArchived):
        rewards.grant_manual(rule, participant, admin_id="a")
```

and one API test: `test_draw_on_an_archived_quiz_answers_409(admin_client, archived_run)`.

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/domain tests/api -k archived_quiz -v`.

- [ ] **Step 3: Implement** — first statement of each listed domain function: `authoring.ensure_editable(run.quiz)` (resolve the run from the rule, entitlement, answer or participant). Add `except authoring.QuizArchived` in the listed views. Mind the `rewards`↔`authoring` import direction (TD-049): import inside the function if a cycle appears, with a comment.

- [ ] **Step 4: Run, expect PASS**; `uv run pytest tests/domain tests/api -q`.

- [ ] **Step 5: Update `docs/_architecture/modules/domain.md:110`** if its wording now needs the list of guarded operations; commit — `fix(domain): archived quiz refuses grading, rewards, draws and run changes`

### Task A4: `attempt.submitted` is emitted after commit

**Files:**
- Modify: `app/domain/attempts.py:708-770` (`_store`)
- Test: `tests/domain/test_attempts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_submitted_event_fires_once_when_the_store_is_retried(attempt, monkeypatch):
    # first _store call raises OperationalError("database is locked") after the emit point; with_retry runs it again
    assert emitted == 1
    assert emitted_after_commit  # recorded inside transaction.on_commit
```

Use `events.register`/a capture handler as `tests/kernel/test_events.py` does; force the retry by patching `with_retry`'s function to fail once.

- [ ] **Step 2: Run, expect FAIL** (emitted == 2).

- [ ] **Step 3: Implement** — replace `events.emit(...)` in `_store` with `transaction.on_commit(lambda: events.emit("attempt.submitted", payload))`, payload built before the lambda.

- [ ] **Step 4: Run, expect PASS**; `uv run pytest tests/domain/test_attempts.py tests/integration -q`.

- [ ] **Step 5: Commit** — `fix(attempts): emit attempt.submitted after commit`

### Task A5: Manual reward grant requires a submitted attempt

**Files:**
- Modify: `app/domain/rewards.py:646-672` (`grant_manual`)
- Test: `tests/domain/test_entitlements.py`

**Interfaces:**
- Produces: `rewards.NotGrantable(RewardError)` raised when `participant not in grantable(run)`; `admin_rewards.reward_grant` (`admin_rewards.py:486`) answers it with 409 like its other refusals.

- [ ] **Step 1: Failing test** — `test_grant_manual_refuses_a_participant_without_a_submitted_attempt` (participant with an IN_PROGRESS attempt only) expects `rewards.NotGrantable`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** the check as the first statement after `ensure_editable`; map it in the view.
- [ ] **Step 4: Run, expect PASS**; `uv run pytest tests/domain/test_entitlements.py tests/api/test_admin_rewards.py -q`.
- [ ] **Step 5: Commit** — `fix(rewards): manual grant needs a submitted attempt`

### Task A6: Global settings and branding save in one transaction

**Files:**
- Modify: `app/api/admin_settings.py:16-24`, `app/api/admin_forms.py:894-917` (`BrandingForm.save`), `app/api/admin_branding.py` (where `BrandingForm.save` is called for a quiz)
- Test: `tests/api/test_admin_settings.py`, `tests/api/test_admin_branding.py`

- [ ] **Step 1: Failing tests** — `test_a_failed_colour_save_leaves_no_setting_changed` (patch `GlobalSettingsForm.save_colours` to raise; assert every key still at its old value) and `test_a_refused_logo_leaves_texts_unchanged` (second text field changed, image refused via `branding.ImageChangeRefused`; assert texts unchanged — order: images first already, so make the refusal come from `set_texts` of the second field by patching).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — `with transaction.atomic():` around the loop + `save_colours` in `settings_page`, and around the whole body of `BrandingForm.save`. SQLite provider opens IMMEDIATE transactions (`providers/persistence_sqlite/provider.py:24`), so no extra locking.
- [ ] **Step 4: Run, expect PASS**; commit — `fix(admin): settings and branding save atomically`

### Task A7: Partial saves of the quiz row

**Files:**
- Modify: `app/domain/authoring.py:655-660` (`_restore_quiz_fields`), `app/api/admin_quizzes.py:316-319` (`quiz_name`)
- Test: `tests/domain/test_authoring.py`, `tests/api/test_admin_quizzes.py`

- [ ] **Step 1: Failing tests** — `test_restore_keeps_an_archive_done_meanwhile`: load quiz, archive it through a second instance, call the restore path; assert `Quiz.objects.get(pk).archived_at is not None`. Same for `quiz_name` with `quiz_type` changed meanwhile.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — `quiz.save(update_fields=["title", "description", "supported_locales", "default_locale"])` and `quiz.save(update_fields=["title"])`, as `quiz_types.py:213-224` does.
- [ ] **Step 4: Run, expect PASS**; commit — `fix(authoring): partial saves keep concurrent quiz changes`

### Task A8: `jobs` healthcheck also watches the heartbeat

**Files:**
- Modify: `app/domain/heartbeat.py:132-151` (`jobs_healthy`), `app/domain/heartbeat.py` `main(["check"])`
- Test: `tests/domain/test_heartbeat.py`

Keep the deliberate rule "no record yet is healthy" (`test_jobs_healthy_with_no_record_or_nothing_readable`). Add: a `jobs` heartbeat file older than `3 * JOBS_INTERVAL` seconds is unhealthy even when the pass record looks fine.

- [ ] **Step 1: Failing test** — `test_a_stale_jobs_heartbeat_is_unhealthy(tmp_path)`: write a fresh pass record, touch the `jobs` heartbeat file with mtime `now - 3 * JOBS_INTERVAL - 1`; assert `jobs_healthy(now, tmp_path) is False`. And `test_a_missing_jobs_heartbeat_with_a_fresh_record_is_healthy` (first start).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — in `jobs_healthy`, `stale = age("jobs", folder, now.timestamp())`; `if stale is not None and stale > 3 * JOBS_INTERVAL: return False` before the record logic.
- [ ] **Step 4: Run, expect PASS**; `uv run pytest tests/domain/test_heartbeat.py tests/domain/test_jobs_heartbeat.py -q`; commit — `fix(jobs): healthcheck watches the heartbeat too`

### Task A9: Graceful stop in Compose

**Files:**
- Modify: `deploy/compose.yaml:33-56` (`app`, `jobs`)
- Modify: `app/domain/management/commands/jobs.py` (`pass_once` checks `stop` before starting a backup)
- Test: `tests/test_deploy.py` (or the file that already asserts on `deploy/compose.yaml`; find it with `grep -rl compose.yaml tests`), `tests/domain/test_jobs_backup.py`

- [ ] **Step 1: Failing tests** — compose test: `app` has `stop_grace_period: 35s`, `jobs` has `stop_grace_period: 120s` (the values the spec pins: gunicorn graceful 30 s + 5; a backup copies the database and media). Jobs test: `test_a_due_backup_is_skipped_when_stop_is_set` — `pass_once(stop=lambda: True)` records outcome `stopped` and writes no backup directory.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** both; resolve or narrow TD-072 in `TECH_DEBT.md` (`make tech-debt-resolve id=TD-072` if fully covered).
- [ ] **Step 4: Run, expect PASS**; `make smoke` once (ports via `SMOKE_HTTP_PORT`/`SMOKE_HTTPS_PORT` when the browser stack runs); commit — `fix(deploy): graceful stop for app and jobs`

### Task A10: Refuse a weak `KVZ_SECRET_KEY`

**Files:**
- Modify: `app/settings.py:12-18`
- Test: `tests/test_settings.py` (create if absent; load settings through `importlib.reload` with `monkeypatch.setenv`)

- [ ] **Step 1: Failing test** — `test_a_secret_key_shorter_than_32_characters_is_refused` expects `ImproperlyConfigured` with the text `KVZ_SECRET_KEY must have at least 32 characters`; `test_a_32_character_key_is_accepted`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `_secret(name: str, minimum: int = 32) -> str`; update `deploy/.env.example` and `docs/configuration.md` (the test `tests/test_docs.py` guards that file) with the minimum.
- [ ] **Step 4: Run, expect PASS**; commit — `fix(settings): refuse a short secret key`

### Task A11: Admin e-mail change of an unknown admin reports an error

**Files:**
- Modify: `app/api/admin_users.py:133-146` (`_change_email`)
- Test: `tests/api/test_admin_users.py`

- [ ] **Step 1: Failing test** — POST with a random `admin_id` → status 404.
- [ ] **Step 2–4:** implement (`if updated.update(...) == 0: raise Http404`), run, commit — `fix(admin): unknown admin on e-mail change is a 404`

### Task A12: Anonymous participant numbers are stored, not derived

**Files:**
- Modify: `app/domain/models.py:257-281` (`Participant.number: PositiveIntegerField(null=True)`), new migration `app/domain/migrations/00NN_participant_number.py` (data migration fills existing rows in `created_at, id` order per run), `app/domain/participants.py` (assign at creation inside the run's IMMEDIATE transaction: `max(number) + 1`), `app/domain/results.py:348-365` (`_numbers`, `participant_numbers` read the column; loose attempts keep the derived order after the last participant number)
- Test: `tests/domain/test_results_board.py`, `tests/domain/test_migration_00NN.py` (pattern: `tests/domain/test_migration_0020.py`)

- [ ] **Step 1: Failing tests** — `test_a_label_number_survives_the_erasure_of_an_earlier_participant`: three participants, erase the first (`retention.erase_participant` or the function `test_retention_erasure.py` uses), board still shows "Účastník 3" for the third. Migration test: existing rows get 1..n in creation order.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** model, migration, assignment, readers. Fix the docstring at `results.py:349`.
- [ ] **Step 4: Run, expect PASS**; `uv run pytest tests/domain tests/api -q -k "results or scoreboard or retention or migration"`; commit — `fix(results): anonymous numbers are stored on the participant`

### Task A13: Revision switch checks modules before writing

**Files:**
- Modify: `app/domain/attempts.py:455-482` (`_replacement`)
- Test: `tests/domain/test_switch.py`

- [ ] **Step 1: Failing test** — `test_switch_to_a_revision_needing_a_disabled_plugin_writes_nothing`: disable `question.number` (as `tests/api/test_disabled_plugin.py` does), current revision has a number question; `attempts.switch(...)` raises the same error `_require_modules` raises; `Attempt.objects.count()` unchanged and the old attempt still IN_PROGRESS.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — `_require_modules(run.current_revision)` as the first statement after the early return in `_replacement`.
- [ ] **Step 4: Run, expect PASS**; commit — `fix(attempts): revision switch refuses a disabled module before writing`

---

## Phase B — usability

### Task B1: One way to end a run, with confirmation

**Files:**
- Modify: `app/api/jinja2/admin/run.html:193-196` (the POST form becomes a link to `admin_run_close`, `role="button"`, same class)
- Modify: `app/api/admin_runs.py:813-827` (`run_close` POST keeps closing; a submission racing the close is already refused by `attempts`, pin it)
- Test: `tests/api/test_admin_runs.py`, `tests/api/test_play.py` (or the file holding submit tests: `grep -rl "def test_submit" tests/api`)

- [ ] **Step 1: Failing tests** — `test_run_page_has_no_direct_close_form`: the run page HTML contains no `<form ... action=".../close">`, and contains the link to `admin_run_close`. `test_submit_during_close_is_refused_not_500`: close the run between start and submit; submit answers with the status the play view uses for a closed run (find it in `play.py` `_error` `STATUS`), not 500.
- [ ] **Step 2: Run, expect FAIL** (the first).
- [ ] **Step 3: Implement** the template change; keep `run_close` as is.
- [ ] **Step 4: Run, expect PASS**; `make messages` if any string changed; commit — `fix(admin): ending a run always asks first`

### Task B2: New quiz form: slug from the name, default language checked, language names

**Files:**
- Modify: `app/api/admin_forms.py:138-165` (`QuizForm`): `slug` becomes `required=False` with help text "Leave empty to derive it from the name"; `clean()` derives it with `django.utils.text.slugify(title_<default_locale>)[:80]` and keeps `_slug_is_free`; `supported_locales` initial `[settings default locale]`, choice labels the language names (`Čeština`, `English`, `Українська` — the labels the public menu uses, `grep -rn "Українська" app/api`)
- Modify: `app/api/jinja2/admin/quiz_form.html`: the quiz type block opens by default (`<details open>` or equivalent) on the new form only
- Test: `tests/api/test_admin_quizzes.py`, `tests/api/test_admin_forms.py`

- [ ] **Step 1: Failing tests**

```python
def test_new_quiz_without_slug_derives_it_from_the_name(admin_client):
    # title_cs="Vánoční kvíz 2026" -> slug "vanocni-kviz-2026"
def test_new_quiz_with_a_whitespace_name_shows_the_name_error(admin_client):
    # title_cs="   ", no slug -> 200, error on title, no quiz created
def test_new_quiz_form_preselects_the_default_language(admin_client):
    # GET: the cs checkbox is checked, labels contain "Čeština"
def test_new_quiz_form_shows_the_quiz_type_open(admin_client)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; a derived slug that is taken gets `-2`, `-3` … (reuse `_free_slug` from `admin_quizzes.py:748`).
- [ ] **Step 4: Run, expect PASS**; `make messages`; commit — `feat(admin): new quiz derives the address and preselects the language`

### Task B3: Focus moves to the first question after start

**Files:**
- Modify: `app/api/assets/flow.js:108-132` (`show(index, moveFocus)`): on the first render after an HTMX swap of `#play` triggered by the start or resume form, call `show(first, true)` so `sections[first].focus()` runs; the heading "Question 1 of N" element gets `tabindex="-1"` in `app/api/jinja2/public/_questions.html` and is the focus target when there is no `.flow-reveal`
- Test: `tests/api/test_countdown_script.py` style script test (the project tests JS by reading the file: `grep -n "flow.js" tests -r`), plus the browser walkthrough

- [ ] **Step 1: Failing test** — `test_flow_script_moves_focus_after_start`: `flow.js` contains the start-swap hook (assert on the exact function name chosen, e.g. `focusFirstStep`), and `_questions.html` renders `tabindex="-1"` on the progress heading.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** in `flow.js`: listen to `htmx:afterSwap` on `#play`; when `event.detail.requestConfig.elt` is `[data-start-form]` or the resume form, call `show(first, true)`.
- [ ] **Step 4: Run, expect PASS**; walkthrough per `kvizotron-browser-walkthrough`: after Enter on "Začít" the active element is the question section or heading; Shift+Tab goes to the skip link (Review Focus 4).
- [ ] **Step 5: Commit** — `fix(play): focus the first question after start`

### Task B4: Submitting with unanswered questions asks first

**Files:**
- Modify: `app/api/assets/flow.js` (before the submit request: count sections without a value — radio/checkbox checked, text/number non-empty, select chosen, file chosen — and `confirm()` with the text from `data-unanswered-confirm`; cancel stops the request via `htmx:confirm`)
- Modify: `app/api/jinja2/public/_questions.html:5` — `data-unanswered-confirm="{{ _('%(count)s questions have no answer. Submit anyway?') }}"` (with `{count}` placeholder like `data-progress-step`)
- Test: script test as in Task B3; browser walkthrough (the automatic submission at the time limit must NOT ask: `countdown.js` submits through its own path — pin with a test that the confirm hook ignores requests flagged by the countdown)

- [ ] **Step 1: Failing tests** — `test_questions_form_carries_the_unanswered_text`, `test_flow_script_asks_before_an_incomplete_submission`, `test_automatic_submission_does_not_ask`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; `make messages` (cs: "%(count)s otázek je bez odpovědi. Přesto odeslat?", uk by the translator rule in `tools/messages.py`).
- [ ] **Step 4: Run, expect PASS**; walkthrough: submit with two blanks shows the confirm; "Cancel" stays on the page; countdown end submits without a dialog.
- [ ] **Step 5: Commit** — `feat(play): ask before submitting unanswered questions`

### Task B5: Scoreboard rows on a phone stay one line

**Files:**
- Modify: `app/plugins/theme_default/assets/theme.css:1825-1860` (`table.stack` under 48rem): a new class `table.stack.compact` keeps `tr` as a flex row: place, name (grows, ellipsis), score, percent; `data-label` hidden for `compact`
- Modify: `app/api/jinja2/public/_scoreboard_rows.html:8` → `<table class="stack compact">`
- Test: `tests/api/test_scoreboard.py` (class present), browser walkthrough at 390 px with 5 rows

- [ ] **Step 1: Failing test** — the rows fragment renders `class="stack compact"`.
- [ ] **Step 2–4:** implement, run, walkthrough screenshot (one line per row, name truncated with ellipsis at 30 characters), commit — `fix(theme): compact scoreboard rows on phones`

### Task B6: First publication shows a summary instead of a full diff

**Files:**
- Modify: `app/api/admin_quizzes.py:669-685` (`_publish_page`): when `published is None`, pass `summary` (`question count`, `max points`, `locales`) and no `diff`
- Modify: `app/api/jinja2/admin/publish.html:25`: `{% if diff %}` include `_diff.html` `{% else %}` a three-line summary `{% endif %}`
- Test: `tests/api/test_admin_quizzes.py`

- [ ] **Step 1: Failing test** — `test_first_publication_shows_a_summary_not_a_diff`: page contains "3 questions · 3 points · cs, uk" (exact wording chosen in the template through `_()`), does not contain the "Before" column header.
- [ ] **Step 2–4:** implement, `make messages`, run, commit — `feat(admin): first publication shows a summary`

### Task B7: Closed quiz page answers 200

**Files:**
- Modify: `app/api/public.py:169` (`status=404` → `status=200` for the "not running now" page; keep 404 for an unknown slug)
- Test: `tests/api/test_public.py` (or where `unavailable` is tested: `grep -rn "unavailable" tests/api`)

- [ ] **Step 1: Failing test** — closed run: 200 with the "not running" text; unknown slug: 404.
- [ ] **Step 2–4:** implement, run, update `docs/_architecture/security.md` if it states the 404 rule (`grep -n 404 docs/_architecture/security.md`), commit — `fix(public): a quiz that is not running answers 200`

---

## Phase C — TD-101 and TD-036: values an open run reads live

### Task C1: ADR proposal (stops for a human)

**Files:**
- Create: `docs/_architecture/adr/0064-run-copies-flow-and-profile.md` (MADR 4, status `proposed`)
- Modify: `docs/_architecture/open-questions.md` (new row OQ-15), `docs/_architecture/adr/README.md` or index (`tests/test_docs.py` checks the index range)

- [ ] **Step 1: Write the ADR** with two options: (a) copy navigation, reveal, shuffle, sources and the answers-visibility profile onto `QuizRun` at planning/opening, read them from the run (the solution text of TD-101 and TD-036); (b) keep live reading and make the quiz-type bar and the settings page warn for an open run. Recommendation: (a), because the time limit, participants, data profile, scoreboard and rewards already work that way and the test add-ons spec kept reveal live only for lack of time.
- [ ] **Step 2: Run `uv run pytest tests/test_docs.py -q`** — PASS.
- [ ] **Step 3: Commit** — `docs: ADR-0064 proposed, run copies flow and profile`
- [ ] **Step 4: STOP.** Ask the user to decide the ADR. Tasks C2–C3 run only with status `accepted` for option (a). If (b) is chosen, replace C2–C3 with the warning in `_quiz_type_bar.html` and `quiz_settings.html` and resolve TD-101/TD-036 as "decided: live".

### Task C2: Run copies flow values at planning and opening

**Files:**
- Modify: `app/domain/models.py` (`QuizRun.flow_json: JSONField(null=True)`), migration `00NN_run_flow` (data: copy `settings.flow(quiz)` of the quiz into every OPEN/PLANNED run)
- Modify: `app/domain/run_schedule.py` (planning) and `app/domain/authoring.py` (`open_run`, `publish_and_open`): fill `flow_json` from `settings.flow(quiz)` plus `show_sources`, `reveal moment`
- Modify: `app/domain/attempts.py:234` (`settings.flow(run.quiz)` → `run.flow_json`), `app/api/rendering.py:237` (`show_sources` from the run), `app/domain/rewards.py:211` (reveal from the run)
- Modify: `app/api/jinja2/admin/run_plan.html` (the plan shows these values like the other copied ones)
- Test: `tests/domain/test_flow_settings.py`, `tests/domain/test_run_schedule.py`, `tests/domain/test_reveal.py`, `tests/domain/test_migration_00NN.py`

- [ ] **Step 1: Failing tests** — `test_a_navigation_change_does_not_reach_an_open_run`, `test_a_sources_change_does_not_reach_a_finished_result_page`, `test_a_reveal_change_does_not_change_reward_rules_of_an_open_run`, migration test.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; the `kvizotron-add-setting` skill applies for the run-level copy (no new catalogue key, but the run plan gains rows).
- [ ] **Step 4: Run, expect PASS**; `make quality`; commit — `feat(runs): navigation, reveal, shuffle and sources are copied to the run (ADR-0064)`

### Task C3: Answer visibility judged by the run's frozen profile

**Files:**
- Modify: `app/domain/settings.py` (`visibility_conflict`, `answers_visibility` take the run profile), `app/domain/visibility.py` callers
- Test: `tests/domain/test_results_settings.py` or `tests/domain/test_stored_answers.py`

- [ ] **Step 1: Failing test** — `test_visibility_follows_the_run_profile_not_the_quiz`: run opened with profile `score`, quiz changed to `answers`; the result page of the run shows no answers.
- [ ] **Step 2–4:** implement, run, `make tech-debt-resolve id=TD-036` and `id=TD-101`, commit — `fix(results): visibility uses the run's frozen profile`

---

## Phase D — housekeeping

### Task D1: Compiled catalogs stop drifting

Decision recorded in `CLAUDE.md`: "`.po` i `.mo` jsou v gitu". Keep that, make the build reproducible.

**Files:**
- Modify: `tools/messages.py:60-65` (`write_mo`): sort the catalog by `msgid` before writing and strip volatile header fields (`POT-Creation-Date`, `PO-Revision-Date`) from the `.mo` header; or, if babel's output still differs byte-for-byte, write with `msgfmt`-compatible ordering via `babel.messages.mofile.write_mo(..., use_fuzzy=False)` after `catalog.header_comment = ""`
- Test: `tests/test_messages.py` (new): `test_make_messages_is_reproducible` — run `tools.messages` twice into a temp copy, compare bytes; and after one run on the real tree `git status --porcelain -- '*.mo'` is empty

- [ ] **Step 1: Failing test** (the second assertion fails today: 42 files).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**; regenerate once; commit the resulting `.mo` files in the same commit.
- [ ] **Step 4: Run, expect PASS**; commit — `chore(i18n): reproducible .mo catalogs`

### Task D2: Untracked files out of the root

**Files:**
- Modify: `.gitignore` (add `report.md`? no: the Heimdall audit belongs outside the repo), move or delete per the user's answer
- Untracked today: `report.md`, `kvizotron_v4/`, `tmp-old/` (9 MB), `.superpowers/`, `kviz_eu_cr_25_otazek.json`, `kviz_eu_cr_banka.csv`, `kv_z_17_listopad_st_tnost_a_evropa.md`

- [ ] **Step 1: Ask the user** which of these to keep; the agent deletes only what it created (memory rule). Proposed: `.superpowers/` → `.gitignore`; `tmp-old/`, `kvizotron_v4/`, `report.md` → move out of the repo; the three `kviz_*` sources → `docs/examples/` if they are sample quizzes, else out.
- [ ] **Step 2: Apply the answer**; `git status --porcelain` shows only intended files.
- [ ] **Step 3: Commit** — `chore: ignore agent state, move stray files`

### Task D3: Shared admin helpers

**Files:**
- Create: `app/api/admin_common.py` with `admin_id(request) -> str`, `uuid_or_404(value: str) -> UUID`, `plain(text) -> str`, `refusal(code: str) -> str` (one mapping of domain refusal codes), `locale_of(request) -> str`, `back_url(request, default: str) -> str`, `confirm_page(request, *, message: str, action: str, cancel: str) -> HttpResponse` (the `admin/confirm.html` renderer `run_close` already uses)
- Modify: `admin_grading.py:316`, `admin_import.py:57`, `admin_results_export.py:39` (`_admin`); `admin_banks.py:492`, `admin_rewards.py:451` (`_uuid`); `admin_links.py:36`, `admin_grading.py:87` (`_plain`); `admin_users.py:55`, `admin_runs.py:137`, `admin_results_export.py:147`, `admin_retention.py` (`_refusal`); `admin_preview.py:70`, `admin_results_export.py:43` (`_locale`); `admin_banks.py:185`, `admin_grading.py:247`, `admin_import.py:98` (`_back`); the seven inline confirm pages listed in the spec §4
- Test: `tests/api/test_admin_common.py` (new, one test per helper); existing API tests stay green

- [ ] **Step 1: Write the helper tests** (pure functions; `refusal` covers every code the four `_refusal` copies know).
- [ ] **Step 2: Run, expect FAIL** (module missing).
- [ ] **Step 3: Create the module, replace each copy, delete the copies.** `tests/test_wiring.py` must still pass (`make wiring`).
- [ ] **Step 4: `make quality`**; commit — `refactor(admin): shared helpers in admin_common`

### Task D4: Split `admin_forms.py` and `play.py`

**Files:**
- Create: `app/api/admin_forms_quiz.py` (QuizForm, DuplicateQuizForm, QuizNameForm, settings forms), `app/api/admin_forms_branding.py` (BrandingForm and colour helpers), `app/api/admin_forms_rewards.py`; `app/api/admin_forms.py` keeps imports for compatibility (`from .admin_forms_quiz import *` is not allowed by ruff — re-export explicitly)
- Create: `app/api/play_errors.py` (`_error`, `STATUS`, `_message_fragment`, `_limited`), `app/api/play_switch.py` (`switch`, `revision_status`, `check`); `play.py` keeps `start`, `resume`, `enter_code`, `submit`, `attempt_time`
- Test: no new behaviour; `make quality` and `make wiring` green; `tests/test_wiring.py` lists the moved views if it names them

- [ ] **Step 1: Move the branding forms first, run `make test`, commit.**
- [ ] **Step 2: Move the quiz/settings forms, run, commit.**
- [ ] **Step 3: Move play error helpers, run `uv run pytest tests/api -q`, commit.**
- [ ] **Step 4: Move the switch views, run, commit** — `refactor(api): split admin_forms and play into focused modules`

---

## Phase E — release checks

### Task E1: Load test and restore drill

**Files:**
- Modify: `docs/_architecture/TECH_DEBT.md` (anything the run surfaces), `docs/deployment.md` only if the drill finds a wrong step

- [ ] **Step 1: `make load`** (project `kvizotron-load`; minutes). Expected: every line `PASS`, exit 0. Paste the summary lines into the task notes.
- [ ] **Step 2: Restore drill** per `docs/deployment.md`: `manage.py backup`, then `manage.py restore latest` on a stopped stack, then start and open a quiz. Expected: the quiz and its attempts are present; `pre-restore-<time>` directory exists.
- [ ] **Step 3: Browser walkthrough** of Phase B changes with the `kvizotron-browser` stack (new quiz, start, end run, phone scoreboard) per `kvizotron-browser-walkthrough`; `errs` empty.
- [ ] **Step 4: Record** each failure as `make tech-debt-create title="…"` or fix it in a new task; commit — `docs: release checks of 2026-11-xx`

---

## Self-review notes

- Spec coverage: §3 findings 1–13 → A1–A13 (finding 1 → A2, 2 → A1, 3 → A3, 4 → A4, 5 → A5, 6 → A6, 7 → A7, 8 → A8, 9 → A9, 10 → A10, 11 → A11, 12 → A12, 13 → A13). §2 admin A1/A2 → B1/B2; participant P1/P2/P3/P4 → B3/B4/B7/B5; A3 → B6. §6 item 4 → Phase C; item 5 → Phase D; item 6 → Phase E; item 1 excluded on request. Not planned: §3 "plausible" items and the N+1 list (defer to TECH_DEBT entries, create them in Task E1 if still open), A4–A8 admin page length, §5 compose hardening beyond `stop_grace_period`, the 306 untranslated `uk` admin strings (documented as intentional).
- Names used across tasks: `_open_refusal` (A1 only), `rewards.NotGrantable` (A5 and its view), `Participant.number` (A12), `QuizRun.flow_json` (C2, C3), `admin_common` helpers (D3). No task reuses a name another defines differently.
- Each test step names its test and its assertion; code steps give the signature or the exact edit and leave the body to the implementer.

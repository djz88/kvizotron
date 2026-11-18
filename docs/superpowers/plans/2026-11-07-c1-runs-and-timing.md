# C1 Runs and timing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan a run with a start and a deadline, limit the time of an attempt, show a countdown with automatic submission, archive ended runs, and show every time in one configured zone.

**Architecture:** Run status changes are applied lazily by one idempotent domain function, `run_schedule.settle`, called from a middleware, so no background process exists. Submissions never depend on that status for timing: `attempts` computes `ends_at` from the deadline and the limit copied onto the attempt, and compares it with the receipt time. The countdown is a small script fed by seconds remaining from the server.

**Tech Stack:** Python 3.15, Django 6.1, Jinja2, HTMX, Pico CSS, SQLite (WAL, `IMMEDIATE`, 20 s busy timeout), Caddy, Docker Compose, uv, Babel catalogues.

**Spec:** `docs/superpowers/specs/2026-11-07-c1-runs-and-timing-design.md`

**Branch:** `feat/c1-runs-and-timing` from `main`.

## Global Constraints

- Boundary: `whole_second(received_at) <= whole_second(min(deadline_at, started_at + limit))`. With 10:00:00, 10:00:00.9 is accepted and 10:00:01.0 rejected (`AC-07`, ADR-0025).
- Automatic submission about 5 s before the end. Polling every 30 s and on tab visible.
- New deadline at least 60 s ahead. Clock panel warns over 60 s of difference or on a different zone.
- Limit: whole minutes 1 to 1440; stored value `"0"` means no limit; default `"0"`.
- Time zone default `Europe/Prague`, one per installation.
- Every text in cs, en, uk through `make messages`; a run is `běh` / `run`, never `kolo`. Comments and identifiers in English.
- Phone width, light and dark, keyboard. No build step. CSP stays `default-src 'self'`: scripts are files in `app/api/assets/`, no inline script.
- No answers or personal data in logs. Clients are never trusted for time.
- Do not delete or recreate `kvizotron-browser` data; verification uses a new quiz. Smoke on free ports: `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke`.
- Each behaviour change has a test that failed first. `make test` must stay green at the end of each task.

## Review Focus

1. Half-filled answers at the automatic submission (a blank in a number, half a matching, a refused photo): the attempt must still be stored, with those questions unanswered, instead of being lost. Tests in Task 6.
2. A submission received in the boundary second while another request has already closed the run: it must count. Test in Task 4.
3. A stale countdown: the deadline moved earlier with a page open, or the tab asleep through the end. The page must learn the true time and not count on past it. Test in Task 5 for the server, browser check in Task 10.
4. Readers of `quiz.runs` meeting a planned or archived run: start-again logic, grading, last run on the public page. A planned run must never look like one that happened. Tests in Task 2 and Task 9.
5. Times entered around a clock change, and an admin whose browser sits in another zone: the form must read them in the configured zone and say which. Tests in Task 1.

---

### Task 1: Time zone and clock panel

**Files:**
- Create: `app/domain/clock.py`, `app/api/jinja2/admin/_clock.html`, `app/api/assets/clock.js`, `tests/support/clock.py`, `tests/domain/test_clock.py`
- Modify: `app/domain/settings.py`, `app/api/jinja.py`, `app/api/admin_links.py`, `app/api/admin_workspace.py`, templates using `strftime` (`admin/runs.html`, `admin/revisions.html`), `app/api/jinja2/admin/settings.html`, `pyproject.toml`/`uv.lock` only if Step 6 says so
- Test: `tests/api/test_admin_settings.py`, `tests/api/test_test_links.py`

**Interfaces:**
- Produces: `settings.TIME_ZONE = "time_zone"`; `settings.zone() -> ZoneInfo`; `clock.whole_second(value: datetime) -> datetime`; `clock.parse_local(value: str) -> datetime` (aware UTC; raises `ValueError`); `clock.shown(value: datetime | None) -> str`; Jinja filter `when` (`clock.shown`) and global `server_clock() -> dict` with keys `epoch`, `text`, `zone`, `utc`; `tests.support.clock.freeze(monkeypatch, when: datetime) -> None`, which patches `django.utils.timezone.now`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_time_is_read_in_the_configured_zone(db):
    settings.set_global(settings.TIME_ZONE, "Europe/Prague", admin_id=None)
    assert clock.parse_local("2026-11-12T18:00") == datetime(2026, 11, 12, 17, 0, tzinfo=UTC)

def test_a_time_skipped_by_the_clock_change_is_refused(db):
    with pytest.raises(ValueError):
        clock.parse_local("2027-03-28T02:30")

def test_an_ambiguous_time_takes_the_first_occurrence(db):
    assert clock.parse_local("2026-10-25T02:30") == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)

def test_a_shown_time_names_the_zone(db):
    assert clock.shown(datetime(2026, 11, 12, 17, 0, tzinfo=UTC)) == "2026-11-12 18:00 CET"

def test_no_time_shows_a_dash(db):
    assert clock.shown(None) == "–"

def test_time_zone_is_not_offered_on_a_quiz():
    assert settings.TIME_ZONE not in settings.keys_for("quiz")

def test_test_link_end_is_read_in_the_configured_zone(logged_in, quiz):
    ...  # POST expires_at=2030-01-01T12:00; link.expires_at == 11:00 UTC
```

- [ ] **Step 2: Run them.** `uv run pytest tests/domain/test_clock.py -q`. Expected: FAIL, no module `clock`.

- [ ] **Step 3: Implement the setting and `clock`**

`TIME_ZONE` joins `CATALOGUE` with `choices=tuple(sorted(available_timezones()))`, identity labels, scopes `("global",)`, reason "One installation serves one place, and different zones in one list would mislead." A skipped time is one where `fold=0` and `fold=1` give offsets in the unusual order, or a round trip through UTC changes the wall clock. `shown` uses `%Y-%m-%d %H:%M %Z`.

- [ ] **Step 4: Replace every display.** All `strftime` in `app/api` and `TIME_FORMAT` in `admin_links.py` go through `clock.shown` / `|when`; `admin_links._end` uses `clock.parse_local`. Afterwards `grep -rn strftime app/api` finds nothing outside `clock.py`.

- [ ] **Step 5: Clock panel.** `_clock.html` renders server time, zone and UTC from `server_clock()`, and an empty browser row filled by `clock.js` from `Date` and `Intl.DateTimeFormat().resolvedOptions().timeZone`. A warning with `role="alert"` when `|browser - epoch| > 60 s` or the zones differ. Include it on `settings.html` in this task; Tasks 3 and 5 include it on the plan form and the run page. Without JS the browser row stays hidden.

- [ ] **Step 6: Check zone data in the image.** `docker compose ... run --rm app python -c "import zoneinfo; print(len(zoneinfo.available_timezones()))"`. Expected: more than 300. If 0, add a pinned `tzdata` with its reason in the commit message.

- [ ] **Step 7: Run tests, translate, commit.** `make messages && make test`. Expected: all pass. Commit `feat: configured time zone and a clock panel`.

### Task 2: Run schedule in the domain

**Files:**
- Create: `app/domain/run_schedule.py`, `app/api/run_clock.py`, `app/domain/migrations/00NN_run_schedule.py`, `tests/domain/test_run_schedule.py`
- Modify: `app/domain/models.py`, `app/domain/settings.py`, `app/domain/authoring.py`, `app/domain/quiz_state.py`, `app/settings.py`, `tests/settings.py` if it lists middleware, `app/api/public.py`, `app/api/admin_grading.py`

**Interfaces:**
- Consumes: `clock.whole_second`.
- Produces on `QuizRun`: `Status.SCHEDULED`; fields `starts_at`, `deadline_at` (nullable datetimes), `attempt_limit_sec` (nullable int), `opened_at` (now nullable, set when the run opens). Constraint `one_open_run_per_quiz` covers `SCHEDULED` and `OPEN`.
- Produces: `settings.ATTEMPT_LIMIT = "attempt_limit"`; `settings.attempt_limit_seconds(quiz: Quiz) -> int | None`.
- Produces in `run_schedule`: `settle(now: datetime | None = None) -> None`; `plan(quiz, *, starts_at: datetime, deadline_at: datetime | None, limit_sec: int | None, admin_id: str) -> QuizRun`; `update_plan(run, *, starts_at, deadline_at, limit_sec, admin_id) -> None`; `cancel_plan(run, *, admin_id) -> None`; `start_now(run, *, admin_id) -> None`; `planned_run(quiz) -> QuizRun | None`; `set_deadline(run, deadline_at: datetime | None, *, admin_id: str) -> None`; `in_progress(run) -> int`; exception `ScheduleRefused(code: str)` with codes `start_in_past`, `deadline_before_start`, `deadline_too_soon`, `already_planned`, `not_open`, `not_planned`.
- Produces in `authoring`: `open_run(quiz, *, admin_id, deadline_at: datetime | None = None, limit_sec: int | None | Literal["inherit"] = "inherit") -> QuizRun`.
- Produces in `quiz_state`: `QuizState.planned_run`; `MainAction.START_NOW`; `SecondaryAction.START_NOW`, `EDIT_PLAN`, `CANCEL_PLAN`.

- [ ] **Step 1: Write the failing tests** in `tests/domain/test_run_schedule.py`, with time from `freeze`:

```python
def test_a_plan_opens_on_the_first_request_after_its_start()
    # after settle: status OPEN, opened_at == starts_at, one RunRevision, audit run.opened
def test_a_plan_takes_the_newest_published_revision()
    # publish after plan(): run.current_revision is the new one, before and after opening
def test_a_plan_stays_planned_when_requirements_are_unmet()
    # settle at start: still SCHEDULED; meeting them, next settle opens it
def test_the_deadline_closes_only_after_its_whole_second()
    # deadline 10:00:00: settle at 10:00:00.9 stays OPEN; at 10:00:01.0 CLOSED, closed_at == deadline
def test_reaching_the_deadline_emits_run_closed_once()
def test_settle_twice_changes_nothing_more()
def test_a_plan_refuses_a_past_start_and_a_deadline_not_after_it()
def test_only_one_running_or_planned_run()
    # plan() with an open or planned run raises ScheduleRefused("already_planned"); so does open_run
def test_cancel_frees_the_number()
def test_start_now_opens_at_once_and_keeps_the_plans_deadline_and_limit()
def test_open_run_copies_the_inherited_limit()
    # global 20, quiz override 15: attempt_limit_sec == 900; quiz override "0": None
def test_a_quiz_with_a_plan_cannot_be_archived()
def test_set_deadline_refuses_less_than_a_minute_ahead_and_a_closed_run()
def test_set_deadline_none_removes_it_and_is_audited()
def test_a_planned_run_does_not_count_as_the_last_run()   # quiz_state.of(quiz).last_run is None, main == START_NOW
def test_grading_lists_no_planned_run()
```

- [ ] **Step 2: Run them.** `uv run pytest tests/domain/test_run_schedule.py -q`. Expected: FAIL at import.

- [ ] **Step 3: Models and migration.** Existing rows keep their `opened_at`. `make test` must show no migration drift.

- [ ] **Step 4: Setting.** `ATTEMPT_LIMIT` in `CATALOGUE`: `choices=("0", *map(str, range(1, 1441)))`, default `"0"`, labels `"0"` = "No limit" and the rest "%(n)s minutes", scopes `QUIZ_WIDE`, reason "It counts from the start of an attempt, so a question has no use for it."

- [ ] **Step 5: `settle`.** Opening: `filter(pk=..., status=SCHEDULED).update(status=OPEN, opened_at=starts_at)` inside `atomic`, and the `RunRevision` and audit (`actor_type="system"`) only when it changed one row. Closing: open normal runs with `deadline_at__lt=whole_second(now)`; same conditional update with `closed_at=deadline_at`, audit, `run.closed`. Two cheap selects and no write when nothing is due. Test runs are not touched, as they have no schedule.

- [ ] **Step 6: Middleware.** `RunClockMiddleware` in `app/api/run_clock.py`, last in `MIDDLEWARE`, calls `settle()`. A database error there is logged and does not fail the page, because `attempts` does not depend on it.

- [ ] **Step 7: Publication.** `authoring.publish` sets `current_revision` of a planned run in the same transaction. Archiving refuses with a planned run as with an open one. `public.py` and `admin_grading.py` leave `SCHEDULED` out of "last run" and grading.

- [ ] **Step 8: Run tests, commit.** `make test`. Expected: all pass. Commit `feat: run schedule, deadline and inherited time limit in the domain`.

### Task 3: Planning in admin

**Files:**
- Create: `app/api/jinja2/admin/run_plan.html`, `tests/api/test_run_plan.py`
- Modify: `app/api/admin_runs.py`, `app/api/admin_urls.py`, `app/api/admin_forms.py`, `app/api/jinja2/admin/_actions.html`, `app/domain/quiz_state.py`, `app/api/jinja2/admin/quiz_settings.html` if the field needs help text

**Interfaces:**
- Consumes: Task 2's `run_schedule` and `QuizState`; `clock.parse_local`.
- Produces: URL names `admin_run_plan` (`quizzes/<id>/plan`, GET/POST), `admin_plan_edit` (`runs/<id>/plan`), `admin_plan_cancel` and `admin_plan_start` (`runs/<id>/plan/cancel`, `/start`, POST); `RunPlanForm` with fields `starts_at`, `deadline_at`, `limit_minutes`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_one_click_start_is_unchanged()      # POST admin_run_open: OPEN, deadline None, inherited limit
def test_plan_link_sits_next_to_start()          # 'Plan…' link on the quiz page with no run
def test_empty_start_opens_at_once_with_deadline_and_limit()
def test_limit_is_prefilled_from_inheritance()   # quiz override 15: form initial 15
def test_empty_limit_means_no_limit_for_this_run()
def test_refusals_show_a_message_and_keep_the_form()  # past start, deadline before start, 1441 minutes
def test_plan_with_changes_and_nothing_published_is_refused()
def test_planned_quiz_shows_start_now_edit_and_cancel()
def test_unmet_requirements_on_a_due_plan_are_shown_on_the_quiz()
def test_limit_override_on_quiz_form_empty_inherits_and_zero_means_none()
def test_global_limit_field_is_a_number_not_a_list()   # <input type="number"> with min 0 max 1440
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Forms.** In `GlobalSettingsForm` and `QuizBehaviourForm`, `ATTEMPT_LIMIT` is an integer input (0 to 1440, 0 means no limit), not a `ChoiceField`; on the quiz form empty means inherit, and the help text says what is inherited. Saved as the string the catalogue expects. `TIME_ZONE` stays a select.

- [ ] **Step 4: Views and templates.** `_actions.html` follows the new states; with a plan and unpublished changes the main action is `PUBLISH_CHANGES` and the plan actions go under the arrow. `run_plan.html` includes `_clock.html` and names the zone beside the fields. Times are entered with `datetime-local`.

- [ ] **Step 5: Run tests, translate, commit.** `make messages && make test`. Expected: all pass. Commit `feat: plan, edit and cancel a run in admin`.

### Task 4: Time enforced on attempts

**Files:**
- Create: `tests/domain/test_attempt_time.py`
- Modify: `app/domain/attempts.py`, `app/api/play.py`, `app/urls.py`, `tests/api/test_play.py`

**Interfaces:**
- Consumes: `clock.whole_second`, `settings.attempt_limit_seconds`, `QuizRun` fields.
- Produces in `attempts`: `ends_at(attempt: Attempt) -> datetime | None`; `remaining(attempt_id: UUID, token: str) -> int | None`; `time_left(attempt: Attempt) -> int | None` for an attempt just loaded by a view; `submit(attempt_id, token, answers, submission_key, received_at: datetime | None = None, lenient: bool = False) -> AttemptResult`. Error code `run_not_started`. `attempt.settings_json["limit_sec"]`.
- Produces URL name `attempt_time`: `POST a/<uuid>/time` with `attempt_token`, answering `{"remaining": int | null}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_submission_in_the_boundary_second_is_accepted()   # AC-07: limit 10:00:00, received 10:00:00.9
def test_submission_after_it_is_rejected()                 # 10:00:01.0: attempt_expired
def test_a_limit_ends_the_attempt()                        # started 10:00, limit 600 s, 10:10:01 rejected
def test_the_earlier_of_deadline_and_limit_wins()
def test_a_moved_deadline_applies_to_attempts_in_progress()
def test_received_in_time_counts_after_another_request_closed_the_run()
    # settle at 10:00:01 closes; submit with received_at=10:00:00.9 is stored
def test_a_manual_close_still_rejects_later_submissions()
def test_without_a_deadline_it_works_until_a_manual_close()
def test_start_before_the_plan_is_refused()                # run_not_started, HTTP 409 with message
def test_start_after_the_deadline_is_refused_before_any_settle()
def test_switching_revision_gains_no_time()                # replacement keeps limit_sec and started_at
def test_a_changed_token_gains_nothing()                   # limit comes from the attempt row, not the token
def test_a_test_link_takes_the_limit_from_the_quiz()
def test_time_answers_seconds_remaining_and_nothing_else()
    # keys == {"remaining"}; no limit: None; ended run: 0; bad token: refused
```

- [ ] **Step 2: Run them.** `uv run pytest tests/domain/test_attempt_time.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.** `attempts.start` copies the limit into `settings_json` (`run.attempt_limit_sec` for a normal run, `settings.attempt_limit_seconds(run.quiz)` for a test run), refuses `SCHEDULED`, and refuses when `ends_at` is past. `_check_still_valid(attempt, claims, received_at)` keeps the token's 24 h check, adds `ends_at`, and replaces the status check with: a closed run rejects only when `whole_second(received_at) > whole_second(run.closed_at)`. `play.submit` takes `timezone.now()` as its first line and passes it on, so storing a photo does not use up the participant's time. `check` and `switch` use the same check.

- [ ] **Step 4: Retry.** Keep `with_retry` and the 20 s busy timeout. The load test in Task 10 confirms this or changes the budget.

- [ ] **Step 5: Run tests, commit.** `make test`. Expected: all pass. Commit `feat: deadline and time limit enforced on attempts`.

### Task 5: Deadline of a running run

**Files:**
- Create: `tests/api/test_run_deadline.py`
- Modify: `app/api/admin_runs.py`, `app/api/admin_urls.py`, `app/api/jinja2/admin/run.html`, `app/api/jinja2/admin/confirm.html`

**Interfaces:**
- Consumes: `run_schedule.set_deadline`, `run_schedule.in_progress`, `attempts.remaining`.
- Produces: URL name `admin_run_deadline` (`runs/<id>/deadline`, POST); `confirm.html` accepts an optional `hidden: Mapping[str, str]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_moving_later_applies_at_once()
def test_moving_earlier_asks_with_the_number_in_progress()   # text includes count; nothing changed until confirmed=1
def test_adding_a_first_deadline_asks_as_well()
def test_removing_the_deadline_applies_at_once()
def test_less_than_a_minute_ahead_is_refused_with_a_message()
def test_the_limit_cannot_be_changed_on_an_open_run()        # no field on run.html; plan edit view on OPEN run: 404
def test_a_page_learns_a_moved_deadline()                    # attempts.remaining drops right after set_deadline
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** The run page shows start, deadline and limit through `|when`, the clock panel and, on an open run, the deadline form.

- [ ] **Step 4: Run tests, translate, commit.** `make messages && make test`. Expected: all pass. Commit `feat: move or remove the deadline of a running run`.

### Task 6: Countdown and automatic submission

**Files:**
- Create: `app/api/assets/countdown.js`, `app/api/jinja2/public/_countdown.html`, `tests/api/test_countdown.py`
- Modify: `app/api/play.py`, `app/api/jinja2/public/_questions.html`, `app/api/jinja2/public/quiz.html`, `app/api/jinja2/public/_result.html`, `app/api/jinja2/public/base.html`, `app/api/public.py`

**Interfaces:**
- Consumes: `attempts.time_left`, `attempts.submit(..., lenient=True)`, URL `attempt_time`.
- Produces: template context `time_left: int | None` on every page that renders `_questions.html`, and `_countdown.html` reading `time_left` and optional `time_url`; form field `auto_submit=1`; result context `time_ran_out: bool`. Task 8 reuses `_countdown.html` without `time_url`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_limit_shows_a_countdown()                 # data-remaining, data-time-url on the page after start
def test_no_time_shows_no_countdown()
def test_switching_keeps_the_real_time()             # after switch, time_left is smaller, not reset
def test_the_quiz_page_states_limit_and_deadline()
def test_it_states_the_real_time_when_the_deadline_shortens_it()
def test_starting_is_not_blocked_close_to_the_deadline()
def test_auto_submit_stores_a_partly_answered_attempt()
def test_auto_submit_treats_an_unreadable_answer_as_unanswered()     # number "abc", half a matching
def test_a_normal_submit_still_refuses_an_unreadable_answer()
def test_auto_submit_drops_a_refused_photo_and_stores_the_rest()     # GIF on an image_answer question
def test_auto_submit_says_the_time_ran_out()
def test_a_repeated_auto_submit_with_the_same_key_stores_once()
def test_a_late_auto_submit_gets_the_expired_message()
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Server.** `auto_submit` only makes `lenient=True` and the message. `lenient` drops an answer that raises `invalid_answer` before scoring; it cannot raise a score. In `play.submit`, with `lenient`, `ImageRefused` removes the files and goes on.

- [ ] **Step 4: `countdown.js`.** Loaded from `public/base.html`, set up on `DOMContentLoaded` and `htmx:afterSwap` as `flow.js` is. The end is `performance.now() + remaining`, corrected by `POST` to `data-time-url` every 30 s and on `visibilitychange`, sending the current `attempt_token` from the form. Display `mm:ss`, or `h:mm:ss` over an hour, in `role="timer"`. A separate `role="status"` element announces at 5 and 1 minutes. At 5 s left, or on loading with less: add `auto_submit=1`, set `form.noValidate = true`, call `form.requestSubmit()`, once. On `htmx:sendError` retry every 2 s, up to 3 times, with the same form. Failed polling is ignored.

- [ ] **Step 5: Run tests, translate, commit.** `make messages && make test`. Expected: all pass. Commit `feat: countdown and automatic submission`.

### Task 7: Planned quiz in public

**Files:**
- Create: `app/api/assets/planned.js`, `tests/api/test_planned_quiz.py`
- Modify: `app/api/public.py`, `app/api/jinja2/public/quiz.html`, `app/api/jinja2/public/landing.html`, `app/api/jinja2/public/base.html`, `app/domain/settings.py`

**Interfaces:**
- Consumes: `run_schedule.planned_run`, `clock.shown`.
- Produces: `settings.ANNOUNCE_PLANNED = "announce_planned"`, values `Switch`, default off, scopes `QUIZ_WIDE`, reason "It concerns a whole quiz on the public list."

- [ ] **Step 1: Write the failing tests**

```python
def test_address_of_a_planned_quiz_shows_title_and_start_without_a_button()
def test_it_shows_this_with_the_announcement_off()
def test_a_planned_quiz_is_not_on_the_list_by_default()
def test_it_is_under_coming_up_when_announced_globally()
def test_a_quiz_override_beats_the_global_value()
def test_a_passed_start_that_could_not_open_says_not_started_yet_without_a_time()
def test_the_page_says_seconds_to_the_start_only_while_it_is_ahead()   # data-starts-in
def test_a_draft_title_does_not_reach_the_page()    # title from the planned revision's snapshot
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** `public.quiz` prefers the open run, then the planned one. `planned.js` reloads once after `data-starts-in` seconds plus a random delay up to 5 s; no polling. `Coming up` is a section under the running quizzes, shown only when not empty.

- [ ] **Step 4: Run tests, translate, commit.** `make messages && make test`. Expected: all pass. Commit `feat: planned quiz on its address and in Coming up`.

### Task 8: Limit in preview

**Files:**
- Modify: `app/domain/preview.py`, `app/api/admin_preview.py`, `app/api/jinja2/public/_mode_bar.html`, `tests/api/test_preview.py`, `tests/api/test_test_links.py`

**Interfaces:**
- Consumes: `settings.attempt_limit_seconds`, `_countdown.html`, `lenient` behaviour from Task 6.
- Produces: `preview.start(quiz, revision, *, timed: bool = False) -> Started`; `preview.check_time(attempt, now: datetime) -> None` raising `AttemptError("attempt_expired")`; GET parameter `timed=1`.

- [ ] **Step 1: Write the failing tests**

```python
def test_preview_has_no_limit_by_default()
def test_the_switch_is_offered_only_when_the_quiz_has_a_limit()
def test_timed_preview_shows_a_countdown_without_polling()   # data-remaining, no data-time-url
def test_a_timed_preview_over_the_limit_is_refused_and_stores_nothing()
def test_reloading_starts_with_the_full_limit()
def test_a_timed_preview_auto_submit_treats_an_unreadable_answer_as_unanswered()
def test_a_test_link_counts_down_and_auto_submits()          # in test_test_links.py
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** `started_at` and `limit_sec` go into the signed token, so the browser cannot extend them.

- [ ] **Step 4: Run tests, translate, commit.** `make messages && make test`. Expected: all pass. Commit `feat: time limit in preview, with a switch`.

### Task 9: Archive and unsent attempts

**Files:**
- Create: `tests/api/test_run_archive.py`
- Modify: `app/domain/run_schedule.py`, `app/api/admin_runs.py`, `app/api/admin_urls.py`, `app/api/jinja2/admin/runs.html`, `app/api/jinja2/admin/run.html`

**Interfaces:**
- Produces in `run_schedule`: `archive(run, *, admin_id) -> None`; `restore(run, *, admin_id) -> None`, each refusing with `ScheduleRefused("not_ended")`; `unsent(run, now: datetime | None = None) -> int`. URL names `admin_run_archive`, `admin_run_restore`. Query `?archived=1` on the runs page.

- [ ] **Step 1: Write the failing tests**

```python
def test_only_an_ended_run_can_be_archived()
def test_it_leaves_the_list_and_returns_with_the_switch()
def test_archive_hides_the_public_walkthrough_and_restore_returns_it()
def test_a_public_photo_of_an_archived_run_is_gone()
def test_a_private_result_link_still_works()
def test_a_participants_own_photo_on_that_link_still_works()
def test_attempts_of_an_archived_run_can_still_be_graded()
def test_archive_and_restore_are_audited()
def test_unsent_on_an_ended_run_counts_all_in_progress()
def test_unsent_on_a_running_run_counts_those_past_their_limit()
def test_unsent_ignores_replaced_attempts()
def test_list_and_run_page_show_planned_status_start_deadline_limit_and_unsent()
```

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** Replacing a status with `SWITCHED` already excludes replaced attempts, as `unsent` counts `IN_PROGRESS` only. An open run counts `started_at + limit < whole_second(now)`, or a past deadline. Attempts of a run with no time apply count 0 until it ends.

- [ ] **Step 4: Run tests, translate, commit.** `make messages && make test`. Expected: all pass. Commit `feat: archive an ended run, count unsent attempts`.

### Task 10: Documentation, load test and verification

**Files:**
- Create: `docs/_architecture/adr/0048-run-timing.md`, `tools/load_deadline.py`
- Modify: `docs/_architecture/modules/domain.md`, `docs/_architecture/modules/api-ui.md`, `docs/_architecture/data-model.md`, `docs/_architecture/acceptance-criteria.md`, `docs/_architecture/roadmap.md`, `docs/_architecture/adr/README.md`, `CLAUDE.md`, `docs/deployment.md` if `tzdata` or the clock matter there

- [ ] **Step 1: Docs.** ADR-0048 records lazy status changes, the limit ending on the run and copied onto the attempt, the global-only zone and the polling. `domain.md` drops the note that status names are a proposal and removes the `ARCHIVED` gap. New AC from `AC-62`: plan and start, moved deadline, automatic submission with bad answers, unsent count, archive, Coming up, time zone. Roadmap marks C1 done; `CLAUDE.md` state updated. `AC-05` and `AC-07` get their Stage checks.

- [ ] **Step 2: Load script.** `tools/load_deadline.py --base URL --run RUN_ID --clients 50`, standard library only: starts 50 attempts, submits all at once, and prints accepted, refused, slowest. It accepts the self-signed local certificate only for `localhost`. Run against a new quiz with a deadline 1 minute ahead.

Expected: `accepted 50, refused 0`, slowest under 5 s. If not, raise the `with_retry` budget, record the value and repeat.

- [ ] **Step 3: Quality.** `make quality`, then `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke`. Expected: all pass, `SMOKE OK`.

- [ ] **Step 4: Browser walkthrough** on a new quiz in `kvizotron-browser`, keeping its data: plan with Coming up on and off; wait for the start with the page open; play with a 1 minute limit until automatic submission in all three navigation modes, with a half-filled matching and a photo question; move the deadline earlier with a page open and watch the countdown correct itself; sleep the tab through the end; end by deadline; restart; archive and restore; timed preview; test link; clock warning with a browser in another zone. Phone width, dark mode, Ukrainian.

Expected: every step behaves as the spec says, and no console errors.

- [ ] **Step 5: Commit.** Commit `docs: milestone C1, runs and timing`.

# D5 follow-up: submissions survive, login limit holds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close TD-022, TD-083, TD-084, TD-051, TD-018, TD-090, TD-081 and TD-041 before `v1.0.0`.

**Architecture:** The limiter in `app/api/rate_limit.py` gains an atomic reserve and release and a second login bucket keyed by address. The login view reserves both slots before `authenticate()`. The automatic submission in `countdown.js` repeats on more failures with a fixed schedule. Small server fixes and two small page scripts complete it.

**Tech Stack:** Django, gunicorn (1 worker, 8 threads), Jinja2, HTMX, plain JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-d5-followup-submit-and-login-design.md`

## Global Constraints

- Login limit values: per name `KVZ_LOGIN_ATTEMPTS_PER_MINUTE` 5 (unchanged), new per address `KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE` 30, both through `_positive_int` in `app/settings.py`.
- Refusal: status 429, `Retry-After: 60`, the existing login message; a correct login never counts.
- Repeat schedule of the automatic submission: 2, 4, 8, 15, 15, 15 s for network error, 5xx and timeout; on 429 wait `Retry-After` (at most 60 s), at most two times; request timeout 15 s only when the form holds no file input.
- Same submission key on every repeat; the server decides what a late send is worth.
- `deploy/compose.yaml` passes the new variable as `NAME: ${NAME:-}`; `docs/configuration.md` has a row for it.
- Texts: public cs/en/uk, admin cs/en; "run", never "round"; `make messages` is run once at the end by the controller (task 9), implementers commit only the catalogs their change touched.
- Documentation in English. New ADR is 0060 and refines ADR-0058.
- No new dependency. Do not touch `kvizotron-browser` data; a new quiz prefix is `d6`.
- `app/api/play.py`, `app/domain/attempts.py` are at least MEDIUM, `deploy/compose.yaml` LARGE: the review of tasks 1, 2, 4 and 6 is a careful one.

## Review Focus

- Parallel wrong logins for one name and address: never more than the limit through (task 1, thread test with a barrier and a slow `authenticate`).
- A correct login right after wrong ones: logs in while there is room, and leaves the slots as they were (task 1).
- A refused login must not leave a slot taken by the refused request itself (task 1).
- One address spraying many names reaches the ceiling while another address is untouched (task 2).
- A 429 from the ceiling and from the per-name bucket look the same to the administrator (task 2).
- A repeat after a 429 must not fire before `Retry-After`, and must stop after two (task 6).
- A form with a file input gets no request timeout (task 6).
- `1,000` warns, `1,5`, `10,00`, `1.000.000` and an empty field do not mis-warn or throw (task 7).

---

### Task 1: Atomic login reservation (TD-090)

**Files:**
- Modify: `app/api/rate_limit.py`, `app/api/admin_auth.py`
- Test: `tests/api/test_rate_limit.py`, `tests/api/test_login_limit.py`

**Interfaces:**
- Produces: `rate_limit.try_acquire(bucket: str, key: str, now: float) -> bool` (checks the window and appends the event under one lock acquisition; raises `KeyError` for an unknown bucket like `allow`), `rate_limit.release(bucket: str, key: str) -> None` (removes the newest event of the key; nothing when there is none). `allow` and `record` stay.

- [ ] **Step 1: tests that fail.** In `test_rate_limit.py`: `test_try_acquire_reserves_and_refuses_past_the_limit` (limit 3: three True, then False), `test_release_gives_back_the_newest_slot`, `test_release_of_an_unknown_key_does_nothing`, `test_try_acquire_never_exceeds_the_limit_under_threads` (50 threads on a `threading.Barrier`, limit 5, exactly 5 True). In `test_login_limit.py`: `test_parallel_wrong_logins_never_exceed_the_limit` (monkeypatch `authenticate` in `app.api.admin_auth` to sleep 50 ms and return `None`; 20 threads on a barrier post the same name and address; the count of non-429 answers equals the limit; mark with AC-129), `test_a_correct_login_leaves_the_slots_as_it_found_them` (four wrong, one correct, then one more wrong is still not refused and the next one is).
- [ ] **Step 2: run, see them fail.**
- [ ] **Step 3: implement** the two functions, and in `admin_auth.login` acquire before `authenticate()` (key `name|address`), release when the login succeeds, keep the slot on a wrong one; a refused acquire answers 429 exactly as now and takes nothing. Remove the `allow`/`record` use from the login view.
- [ ] **Step 4: run** `uv run pytest tests/api -q` and see them pass.
- [ ] **Step 5: commit** `fix(login): reserve the attempt before authenticate so parallel guesses cannot pass`.

### Task 2: Address ceiling across login names (TD-081)

**Files:**
- Modify: `app/api/rate_limit.py`, `app/api/admin_auth.py`, `app/settings.py`, `deploy/compose.yaml`, `docs/configuration.md`
- Test: `tests/api/test_login_limit.py`, `tests/api/test_rate_limit.py`, `tests/api/test_request_limits.py`, `tests/test_configuration_docs.py` (must pass unchanged)

**Interfaces:**
- Consumes: `try_acquire`, `release` from task 1.
- Produces: bucket `"login_address"` in `BUCKETS` and `_SETTING` (setting `KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE`, default 30).

- [ ] **Step 1: tests that fail**: `test_one_address_spraying_many_names_hits_the_ceiling` (limit 3 for the ceiling, name limit 5, one wrong login each for four names from one address: the fourth is 429 with `Retry-After: 60`), `test_the_ceiling_of_one_address_does_not_touch_another`, `test_a_correct_login_does_not_count_toward_the_ceiling`, `test_a_refusal_by_either_bucket_looks_the_same` (same status, message, header), `test_the_ceiling_default_is_30` and the pass-through test for compose in the style of the existing four. Name AC-140 in the first one (a new criterion is written in task 8).
- [ ] **Step 2: run, see them fail.**
- [ ] **Step 3: implement** the bucket and setting, acquire both buckets in the login view (per name then per address; if the second refuses, release the first), release both on success. Add the pass-through line to `x-app` and the row to `docs/configuration.md`.
- [ ] **Step 4: run** `uv run pytest tests/api tests/test_configuration_docs.py tests/test_compose.py -q` (use the compose test file that exists) and see them pass.
- [ ] **Step 5: commit** `feat(login): a ceiling of wrong logins per address across names`.

### Task 3: Vary on the public scoreboard (TD-041)

**Files:**
- Modify: `app/api/scoreboard.py`
- Test: `tests/api/test_security_headers.py` (or the scoreboard test file when the headers test has no scoreboard case)

- [ ] **Step 1: test that fails**: `test_scoreboard_page_and_rows_vary_on_language_and_cookie` for both routes, with and without the run cookie.
- [ ] **Step 2: run, see it fail.** **Step 3:** add `Vary: Accept-Language, Cookie` in both branches of `_cache`, preserving any `Vary` the response already has. **Step 4:** run the scoreboard and header tests. **Step 5: commit** `fix(scoreboard): vary on language and cookie`.

### Task 4: IntegrityError names its cause (TD-051)

**Files:**
- Modify: `app/domain/attempts.py` (`_store`)
- Test: `tests/domain/test_attempts.py` (or the file that already tests `_store`), `tests/domain/test_rewards.py`

- [ ] **Step 1: tests that fail**: `test_an_integrity_error_of_the_submission_key_is_submission_key_used` (keeps working), `test_an_integrity_error_of_another_constraint_is_not_called_a_used_key` (monkeypatch `rewards.refresh` to raise `IntegrityError("UNIQUE constraint failed: other.col")`; the call raises that error, not `AttemptError`), `test_refresh_costs_a_fixed_number_of_queries_for_one_participant` (`django_assert_num_queries` or `CaptureQueriesContext`, record the current number as the bound).
- [ ] **Step 2: run, see the second fail.** **Step 3:** in `except IntegrityError as exc`, convert only when the message names the submission key column or constraint of `Attempt` (look up the real name in the model and the migration; do not guess); otherwise `raise`. **Step 4:** run `uv run pytest tests/domain -q`. **Step 5: commit** `fix(attempts): only the submission key constraint means a used key`.

### Task 5: The form's language on 429 (TD-084)

**Files:**
- Modify: `app/api/jinja2/public/quiz.html` (start form), `app/api/jinja2/public/_questions.html` (submit form)
- Test: `tests/api/test_play_limits.py`

- [ ] **Step 1: tests that fail**: `test_the_start_form_carries_its_language` and `test_the_submit_form_carries_its_language` (rendered `action` and `hx-post` end with `?lang=<locale>` for cs, en and uk; the address the existing tests use for `start` and `submit` still resolves), `test_a_429_on_submit_is_in_the_forms_language` (post with `?lang=uk` and an `Accept-Language: cs` header, assert the Ukrainian message).
- [ ] **Step 2: run, see them fail.** **Step 3:** append `?lang={{ locale }}` to both attributes of both forms, as `revision_status` does; check the `check` and `resume` forms and leave them alone unless they refuse with 429. **Step 4:** run `uv run pytest tests/api -q`. **Step 5: commit** `fix(play): refusals of start and submit use the language of the form`.

### Task 6: Repeat the automatic submission (TD-022, TD-083)

**Files:**
- Modify: `app/api/assets/countdown.js`, the template that holds `#countdown` (find it with `grep -rn 'id="countdown"' app`), `app/api/locale/*` through the usual extraction
- Test: `tests/api/test_countdown_script.py` (new)

**Interfaces:**
- Produces: a hidden note element inside the countdown box with the text "The connection failed. Your answers are being sent again." (cs/en/uk), shown while a repeat is pending.

- [ ] **Step 1: tests that fail** (the script is read as text; there is no JavaScript harness, TD-039): `test_the_script_repeats_on_response_error_timeout_and_429` (asserts `htmx:responseError`, `htmx:timeout`, `htmx:sendError` listeners, the constants of the schedule `[2000, 4000, 8000, 15000, 15000, 15000]` and `Retry-After`), `test_no_timeout_is_set_for_a_form_with_a_file_input` (the script tests for `input[type=file]` before it sets a timeout), `test_the_countdown_box_has_the_waiting_note_in_three_languages` (renders the box in cs, en and uk and finds the note, hidden).
- [ ] **Step 2: run, see them fail.** **Step 3:** implement in `countdown.js`: one handler for the three events, a retry counter and the schedule, `Retry-After` for 429 (cap 60 s, two times), a stop on any other answer, the 15 s timeout set in `htmx:configRequest` only for the automatic submission of a form without a file input, show and hide the note. Same `requestSubmit()` call as now so the submission key is reused. **Step 4:** run `uv run pytest tests/api -q`. **Step 5: commit** `fix(countdown): repeat the automatic submission after a 5xx, a 429 and a timeout`.

### Task 7: Thousands separator note (TD-018)

**Files:**
- Modify: the number question's page script and template under `app/plugins/questions/number/` (add `assets/` if the plugin has none, following another plugin that ships a script), its `locale/*`
- Test: `tests/plugins/questions/test_number_script.py` (new), `tests/contracts` untouched

- [ ] **Step 1: tests that fail**: `test_the_script_matches_exactly_one_separator_and_three_digits` (the pattern in the script, taken from the file, against `1,000`, `1.000`, `-2,500` true and `1,5`, `10,00`, `1.000.000`, `1000`, `` false, evaluated with Python's `re` after the same pattern is written in a form both languages read), `test_the_field_has_the_note_in_three_languages`, `test_the_server_still_grades_1_000_as_one` (`parse_number("1,000") == Decimal(1)`).
- [ ] **Step 2: run, see them fail.** **Step 3:** implement the note (below the field, hidden until the pattern matches, never blocks sending), wording: "`1,000` is read as one (a comma is a decimal sign). For one thousand type 1000." in cs/en/uk. **Step 4:** run `uv run pytest tests/plugins -q`. **Step 5: commit** `feat(number): warn that 1,000 is read as one`.

### Task 8: Documents, acceptance criteria and technical debt

**Files:**
- Create: `docs/_architecture/adr/0060-login-reservation-and-address-ceiling.md`
- Modify: `docs/_architecture/adr/README.md`, `docs/_architecture/adr/0058-rate-limit-buckets.md` ("Refined by ADR-0060"), `docs/_architecture/acceptance-criteria.md` (AC-140 login reservation and address ceiling, AC-141 repeat of the automatic submission and the form's language, AC-142 the scoreboard `Vary` and the number note), `docs/_architecture/security.md`, `docs/deployment.md` (the ceiling and what a restart clears), `docs/configuration.md` (already in task 2: check), `docs/_architecture/TECH_DEBT.md` and the archive through `make tech-debt-resolve id=TD-0NN` for TD-022, TD-083, TD-084, TD-051, TD-018, TD-090, TD-081, TD-041, and the text of TD-087 (the automatic submission is now repeated; a repeated `start` still is not), `app/api/CLAUDE.md`, `tests/CLAUDE.md` if its notes change, `.claude/skills/kvizotron-check-integration/flows.md` (submit and login), root `CLAUDE.md` (a sentence in Stav).
- Test: `tests/test_docs.py` (must pass; the tests of tasks 1 to 7 name AC-140 to AC-142 in a docstring)

- [ ] **Step 1:** write the ADR (context, decision: reserve then release, second bucket, retry schedule, form language, why only the automatic submission is repeated; consequences and the shared-address risk), and the rows above. **Step 2:** name AC-140 to AC-142 in the right tests (docstring or name). **Step 3:** resolve the eight TDs and edit TD-087. **Step 4:** run `uv run pytest tests/test_docs.py tests/test_configuration_docs.py -q` and `make tech-debt-check`. **Step 5: commit** `docs(d5): ADR-0060, AC-140 to AC-142, TD-022 TD-083 TD-084 TD-051 TD-018 TD-090 TD-081 TD-041 closed`.

### Task 9: Verification and handover (controller)

- [ ] `make messages`, then `git status`; commit only what changed.
- [ ] `make quality`, `make smoke` with the ports for the running browser stack, `make wiring`, `make plan-check`.
- [ ] Rebuild the `kvizotron-browser` stack from this branch (secret key from the container, never printed) and run the walkthrough: a new quiz `d6-…`, force a 500 and a 429 on the automatic submission with Playwright route interception and watch the answers arrive and the waiting line come and go, `1,000` shows the note, a 429 on start in uk, the scoreboard `Vary` with `curl -sI`.
- [ ] A fresh reviewer of the whole branch on the most capable model; Critical and Important findings are fixed by a test that fails first.
- [ ] Report: the rulings, what was seen in the browser and what only by tests, and the user's manual step for `deploy/.env.example` (one more commented line `# KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE=30`).

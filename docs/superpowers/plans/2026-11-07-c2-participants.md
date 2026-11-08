# C2 Participants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Runs know who played: repetition rules with an anonymous per-run cookie, name and e-mail collection, duplicate nickname rule, a hashed access code, and an attempts table for the admin.

**Architecture:** A new plugin `participants.basic` (`app/plugins/participants/`) behind a new contract `ParticipantPolicyPlugin` holds the pure decisions (name normalisation, e-mail format, what a returning participant gets) and declares the six settings in its manifest. The domain (`app/domain/participants.py`, `app/domain/access_codes.py`) owns the `Participant` model, the rules snapshot on `QuizRun`, the cookie hash and every check, and calls the plugin through the registry. The API layer sets and reads the two cookies and renders the fields.

**Tech Stack:** Python 3.15, Django 6.1, Jinja2, HTMX, SQLite WAL, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-c2-participants-design.md`

## Global Constraints

- Branch `feat/c2-participants` from `main`. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `make` needs uv 0.13+: `export PATH=<uv-0.13>/bin:$PATH`.
- The plugin imports only `app.contracts` and `app.kernel` (`tests/test_layers.py`). Contracts do not import Django.
- Every setting is declared in a manifest, scopes `["global", "quiz"]` with a `scope_reason` (the whole attempt, ADR-0042). Skill `kvizotron-add-setting` applies.
- Every text in cs, en, uk via `make messages`; a run is `běh` / `run`, never `kolo`.
- No name, e-mail, answer or access code in a log, an audit `details`, the session, a URL or a QR code. E-mail only in the logged-in administration.
- The access code is stored only as `django.contrib.auth.hashers.make_password(code)`.
- Cookie hash: `django.utils.crypto.salted_hmac("kvizotron.participant", f"{run.id}:{key}").hexdigest()`.
- Nickname: displayed `" ".join(name.split())`, compared by `casefold()` of that, max 40 characters.
- Failed access codes: 10 per minute per IP (ADR-0030), in process memory, `KVZ_CODE_ATTEMPTS_PER_MINUTE` overrides.
- Phone width, light and dark, keyboard; no build step.
- New ADR is 0049, new AC from AC-70; each new AC is named by a test (`tests/test_docs.py`).

## Review Focus

1. Two starts or two submissions racing under "forbid" (two tabs): exactly one attempt counts. Tested in Task 3.
2. Resume under "continues" after a revision switch: the attempt found is the `IN_PROGRESS` one at the end of `replaced_by`, not the `SWITCHED` one. Tested in Task 3.
3. The admin changes the code while a participant holds an unlock cookie for the old one: start refused, code form shown again. Tested in Task 5.
4. Nickname made only of spaces, or differing only by case or inner spaces (`"Žába  Ok"` vs `"žába ok"`): empty counts as missing, the others are the same name. Tested in Task 4.
5. Client IP behind Caddy: the limit keys on the first `X-Forwarded-For` value (Caddy overwrites the header from untrusted clients), else `REMOTE_ADDR`. Tested in Task 5; checked in smoke.

---

### Task 1: Contract and plugin `participants.basic`

**Files:**
- Modify: `app/contracts/__init__.py` (Protocol, `PORTS["participant_policy"]`, setting key constants)
- Create: `app/plugins/participants/__init__.py`, `apps.py`, `manifest.py`, `policy.py`, `CLAUDE.md`
- Modify: `pyproject.toml` (entry point `participants.basic = "app.plugins.participants.manifest"` in `kvizotron.modules`, same form as the others)
- Create: `tests/contracts/participant_policy.py`, `tests/contracts/test_participants.py`
- Modify: `docs/plugin-api.md` (new contract section)

**Interfaces:**
- Produces, in `app/contracts`:
  - Keys: `REPEAT_ATTEMPTS = "repeat_attempts"` (`allow`, `forbid`; default `allow`), `UNFINISHED_ATTEMPT = "unfinished_attempt"` (`continue`, `used`, `submitted`; default `continue`), `ASK_NAME = "ask_name"`, `ASK_EMAIL = "ask_email"` (`off`, `optional`, `required`; default `off`), `ASK_WHEN = "ask_when"` (`end`, `start`; default `end`), `DUPLICATE_NAMES = "duplicate_names"` (`allow`, `forbid`; default `allow`). `PARTICIPANT_KEYS: tuple[str, ...]` in that order.
  - `OpenAttempt = Literal["none", "running", "expired"]`; `StartDecision = Literal["new", "resume", "replace", "played", "time_up"]`.
  - `class ParticipantPolicyPlugin(Protocol)`: `clean_name(raw: str) -> str` (collapsed, `""` when empty, `ValueError` over 40); `name_key(clean: str) -> str`; `valid_email(raw: str) -> bool`; `on_start(rules: Mapping[str, str], *, finished: bool, open_attempt: OpenAttempt) -> StartDecision`.
- Registered as `registry.register("participant_policy", "basic", impl, owner="participants.basic")`.

`on_start` table (the plugin's whole job; `replace` = close the open attempt and start new):

| repeat | unfinished | finished | open | result |
|---|---|---|---|---|
| allow | any | any | any | new |
| forbid | any | True | any | played |
| forbid | continue | False | running | resume |
| forbid | continue | False | expired | time_up |
| forbid | used | False | running/expired | played |
| forbid | submitted | False | running/expired | replace |
| forbid | any | False | none | new |

- [ ] **Step 1: Branch.** `git checkout -b feat/c2-participants main`.
- [ ] **Step 2: Write the shared contract suite** `tests/contracts/participant_policy.py` class `ParticipantPolicyContract` with fixture `policy`, tests: `test_clean_name_collapses_spaces` (`"  Žába \t Ok "` → `"Žába Ok"`), `test_blank_name_is_empty` (`"   "` → `""`), `test_name_over_40_is_refused` (`"x"*41` raises `ValueError`, `"x"*40` passes), `test_name_key_ignores_case` (`name_key("Žába Ok") == name_key("žába ok")`), `test_email_format` (`"a@b.cz"` True; `"a@b"`, `"ab.cz"`, `"a b@c.cz"`, `""` False), and `test_on_start_table` parametrised over every row above. `tests/contracts/test_participants.py` subclasses it with the registered implementation.
- [ ] **Step 3: Run** `uv run pytest tests/contracts/test_participants.py -q`. Expected: FAIL, import error.
- [ ] **Step 4: Implement** the Protocol and keys in `app/contracts/__init__.py`, `policy.py` (`BasicParticipantPolicy`; e-mail check: one `@`, non-empty local part, a dot in the domain, no whitespace, max 254), `apps.py` registering it, `manifest.py` (`id "participants.basic"`, `provides ["participant_policy"]`, `activation_scope ["global"]`, `settings` = six declarations with labels, `value_labels`, `help`, `scopes ["global","quiz"]`, `scope_reason` "Applies to the whole attempt, not to one question."), entry point, plugin `CLAUDE.md`, contract section in `docs/plugin-api.md`.
- [ ] **Step 5: Run** `uv run pytest tests/contracts tests/test_layers.py tests/test_wiring.py -q`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(participants): contract and basic policy plugin`.

### Task 2: Models, rules snapshot on the run, plan form

**Files:**
- Modify: `app/domain/models.py`; Create: `app/domain/migrations/0012_participants.py`
- Create: `app/domain/participants.py` (rules part)
- Modify: `app/domain/authoring.py` (`open_run`), `app/domain/run_schedule.py` (`plan`, `update_plan`), `app/api/admin_forms.py` (`RunPlanForm`), `app/api/admin_runs.py` (`_save_new`, `plan_edit`, `_run_context`), `app/api/jinja2/admin/run_plan.html`, `admin/run.html`
- Test: `tests/domain/test_participant_rules.py`, `tests/api/test_run_plan.py`

**Interfaces:**
- Models:
  - `Participant`: `id` UUIDv7, `run` FK `QuizRun` CASCADE `related_name="participants"`, `anonymous_key_hash` CharField(64), `display_name` CharField(40, blank), `name_key` CharField(40, blank), `email` CharField(254, null), `created_at`. Constraint unique (`run`, `anonymous_key_hash`) `participant_key_per_run`; index (`run`, `name_key`). `db_table "participant"`.
  - `Attempt.participant` FK `Participant` null, PROTECT, `related_name="attempts"`. New status `ABANDONED = "abandoned"`; not in `FINISHED`.
  - `QuizRun.participant_rules_json` JSONField default dict; `QuizRun.access_code_hash` CharField(128, blank).
- `participants.rules_for_quiz(quiz: Quiz) -> dict[str, str]`: `settings.resolve(k, quiz=quiz)` for each of `PARTICIPANT_KEYS`.
- `participants.rules_of(run: QuizRun) -> dict[str, str]`: normal run → its snapshot filled with defaults for missing keys; test run → `rules_for_quiz(run.quiz)` with `repeat_attempts="allow"`.
- `participants.needs_identity(rules: Mapping[str, str]) -> bool`: forbid, or name or e-mail not `off`.
- `open_run`, `plan`, `update_plan` take `rules: Mapping[str, str] | None = None`; `None` → `rules_for_quiz(quiz)` at that moment. The snapshot never changes once `OPEN`.
- `RunPlanForm` gets one `ChoiceField` per key, choices and labels from `settings.CATALOGUE`, initial from `rules_for_quiz`; method `rules() -> dict[str, str]`. The form notes that the cookie does not guarantee one person and that "when to ask" applies only when name or e-mail is on.

- [ ] **Step 1: Tests** (`AC-76` in the module docstring): `test_open_copies_rules_from_quiz` (quiz override `repeat_attempts=forbid` → `run.participant_rules_json["repeat_attempts"] == "forbid"`); `test_quiz_change_after_open_does_not_touch_run`; `test_plan_form_overrides_rules` (POST plan with `ask_name=required` → stored); `test_open_run_rules_cannot_change` (`update_plan` on an `OPEN` run raises as today); `test_test_run_reads_quiz_rules_and_allows_repeat`; `test_needs_identity` for the four cases; `test_run_page_lists_rules`.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_participant_rules.py tests/api/test_run_plan.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** models, migration (`makemigrations domain --name participants`), rules functions, wiring into open/plan/update and the forms and templates.
- [ ] **Step 4: Run** the same tests plus `make test`. Expected: PASS, apart from the message catalogue if strings are new (run `make messages`).
- [ ] **Step 5: Commit** `feat(participants): participant model and run rules`.

### Task 3: Cookie identity and repetition

**Files:**
- Modify: `app/domain/participants.py`, `app/domain/attempts.py` (`start`, new `resume`, `submit`/`_store`), `app/api/play.py` (`start`, `submit`, `STATUS`), `app/api/jinja2/public/_message.html` or new `public/_played.html`
- Test: `tests/domain/test_repetition.py`, `tests/api/test_participant_cookie.py`

**Interfaces:**
- `participants.key_hash(run: QuizRun, key: str) -> str` (Global Constraints formula).
- `participants.COOKIE_PREFIX = "kvz_p_"`; cookie name `f"kvz_p_{run.id.hex}"`, value `secrets.token_urlsafe(32)`, `max_age` 30 days, `httponly=True`, `secure=not settings.DEBUG`, `samesite="Lax"`, `path="/"`.
- `participants.find_or_create(run: QuizRun, key: str) -> Participant`.
- `participants.begin(run: QuizRun, participant: Participant | None) -> Begin` with `Begin(decision: StartDecision, attempt: Attempt | None)`; `attempt` is the open one for `resume`/`replace`. Follows `replaced_by` to the live `IN_PROGRESS` attempt. "expired" = `attempts.time_left(attempt) == 0`.
- `attempts.start(run: QuizRun, *, participant: Participant | None = None) -> StartedAttempt`: in one `transaction.atomic()` re-runs `begin`; `played` → `AttemptError("already_played")`, `time_up` → `AttemptError("time_is_up")`, `replace` → the open attempt becomes `ABANDONED`, `resume` → returns `resume(attempt)`.
- `attempts.resume(attempt: Attempt) -> StartedAttempt`: new token for the same attempt, same selection and `settings_json`, new `submission_key`.
- `attempts.submit`: an `ABANDONED` attempt → `AttemptError("attempt_closed")`. Inside `_store`, under "forbid", another `FINISHED` attempt of the same participant → `AttemptError("already_played")`.
- `play.start` reads the cookie, creates it only when `needs_identity(rules_of(run))`, and sets it on the response. `STATUS`: `already_played` 409, `time_is_up` 410, `attempt_closed` 409.
- Refusal page text (cs): "Tento běh už jste v tomto prohlížeči hráli." with a link to the result when the participant has a finished attempt (`tokens.issue_result`), and "Platí jeden pokus na prohlížeč."

- [ ] **Step 1: Tests** (`AC-70`, `AC-71`): `test_allow_never_sets_cookie` (no `kvz_p_` in `response.cookies`, no `Participant` row); `test_forbid_sets_httponly_lax_cookie`; `test_hash_differs_between_runs_for_same_key`; `test_forbid_refuses_second_after_submit`; `test_continue_resumes_same_attempt` (same attempt id, same `selection_json`); `test_continue_expired_is_time_up` (freeze past limit); `test_used_refuses_after_start`; `test_submitted_mode_abandons_previous` (old token submit → 409, new submits); `test_resume_follows_switch_chain`; `test_two_tabs_cannot_both_submit_under_forbid` (two attempts forced into existence for one participant; second submit 409); `test_concurrent_starts_make_one_attempt` (two threads, `transaction=True` DB, one `IN_PROGRESS` attempt).
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_repetition.py tests/api/test_participant_cookie.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces.
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(participants): cookie identity and repetition rules`.

### Task 4: Name and e-mail, duplicates, filling in later

**Files:**
- Modify: `app/domain/participants.py`, `app/domain/attempts.py` (`submit` kwargs), `app/api/play.py` (`start`, `submit`), `app/api/public.py` (`result`, new `result_identity`), `app/urls.py`
- Create: `app/api/jinja2/public/_identity_fields.html`
- Modify: `public/quiz.html`, `public/_questions.html` (fields before `#play-submit`), `public/_result.html`, `public/result.html`
- Test: `tests/domain/test_identity.py`, `tests/api/test_identity_flow.py`

**Interfaces:**
- `participants.Identity(name: str, email: str | None)`; `participants.read_identity(rules, raw_name: str, raw_email: str, *, automatic: bool) -> Identity` raising `AttemptError` `name_required`, `name_too_long`, `email_required`, `email_invalid` (422). With `automatic=True` missing or invalid values become empty instead of errors.
- `participants.claim_name(participant: Participant, identity: Identity, *, automatic: bool) -> None`, called inside the submit transaction: under `duplicate_names=forbid`, another participant of the run with the same `name_key` and a `FINISHED` attempt → manual: `AttemptError("name_taken")` 409; automatic: stored without a name. Only participants with a finished attempt hold a name.
- `attempts.submit(..., identity: Identity | None = None)`.
- Fields: `participant_name`, `participant_email`; rendered by `_identity_fields.html` with one line "Jméno a e-mail slouží jen pořadateli tohoto běhu." and a link to `/privacy`. With `ask_when=start` they are on the quiz page and `play.start` validates them (and checks the name for early feedback); with `end` they are inside the form in `_questions.html` before `#play-submit`.
- Refused manual submit: status 422/409, header `HX-Retarget: #identity-error`, `HX-Reswap: innerHTML`; the form and answers stay; the attempt stays `IN_PROGRESS`.
- `public.result_identity(request, token)` route `v/<token>/identity` name `result_identity`, POST, fills only missing fields, refused once the run is `ARCHIVED`. `_result.html` and `result.html` show the form when a required field is missing or the name was dropped as taken.
- Admin label for an empty name: "bez jména".

- [ ] **Step 1: Tests** (`AC-73`, `AC-74`): `test_required_name_at_end_refuses_manual_without_name` (422, attempt `IN_PROGRESS`); `test_name_before_start_blocks_start`; `test_auto_submit_without_required_name_counts` (score stored, name empty, result page shows the form); `test_fill_in_later_through_result_link`; `test_fill_in_refused_after_archive`; `test_duplicate_forbid_refuses_manual` (`"Žába  Ok"` then `"žába ok"`); `test_duplicate_allow_accepts`; `test_abandoned_attempt_holds_no_name`; `test_auto_submit_taken_name_drops_name`; `test_blank_name_counts_as_missing`; `test_concurrent_same_name_one_wins` (`transaction=True`, two threads); `test_invalid_email_refused`; `test_fields_carry_privacy_link`.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_identity.py tests/api/test_identity_flow.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Check in the browser** (skill `kvizotron-browser-walkthrough`) that a refused name keeps the answers on screen in step mode; the tests see HTML only.
- [ ] **Step 6: Commit** `feat(participants): name and e-mail collection`.

### Task 5: Access code

**Files:**
- Create: `app/domain/access_codes.py`, `app/api/code_limit.py`
- Modify: `app/domain/attempts.py` (`start`), `app/api/play.py` (new `enter_code`), `app/api/public.py` (`_quiz_page`), `app/urls.py`, `public/quiz.html`, `app/api/admin_runs.py` (new `run_code`), `app/api/admin_urls.py`, `admin/run.html`, `admin/run_plan.html`, `app/api/admin_forms.py`, `app/settings.py` (`KVZ_CODE_ATTEMPTS_PER_MINUTE`), `docs/deployment.md`
- Test: `tests/domain/test_access_codes.py`, `tests/api/test_access_code_flow.py`

**Interfaces:**
- `access_codes.ALPHABET`: built in code as `string.ascii_uppercase + string.digits` minus `I`, `L`, `O`, `0`, `1`; `generate() -> str` (8 characters, `secrets.choice`).
- `access_codes.set_code(run: QuizRun, code: str | None, *, admin_id: str) -> None` (`make_password`; `None` or `""` removes; audit `run.code_changed` with `{"removed": bool}` only). Allowed on `SCHEDULED` and `OPEN` runs.
- `access_codes.matches(run: QuizRun, code: str) -> bool` (`check_password`, input stripped and upper-cased).
- `access_codes.unlock_token(run: QuizRun) -> str` and `is_unlocked(run: QuizRun, token: str | None) -> bool`: `signing.dumps({"run": str(run.id), "v": run.access_code_hash[-16:]}, salt="kvizotron.access")`; a changed code changes `v`. Cookie `f"kvz_c_{run.id.hex}"`, same flags as the participant cookie.
- `code_limit.client_ip(request) -> str` (first `X-Forwarded-For` item, else `REMOTE_ADDR`); `code_limit.allow(ip: str, now: float) -> bool`, sliding 60 s window, counts failures only via `code_limit.failed(ip, now)`.
- `attempts.start(run, *, participant=None, unlocked: bool = True)`; a run with a code and `unlocked=False` → `AttemptError("code_required")` 403. Test runs ignore the code.
- `play.enter_code` POST `r/<run_id>/code` name `run_code`: over the limit → 429 with a message; wrong → quiz page with an error; right → unlock cookie and redirect to the quiz page. The QR and the public link stay unchanged.
- Admin: plan form fields `access_code` (optional text) and `generate_code` (checkbox); run page form POST `runs/<id>/code` name `admin_run_code` with set, generate, remove. The new code is shown once in that response (rendered with status 200, not a redirect, not stored in the session).

- [ ] **Step 1: Tests** (`AC-72`): `test_only_hash_is_stored` (no plaintext in `access_code_hash` or the audit row); `test_generated_code_uses_readable_alphabet`; `test_start_without_unlock_is_403`; `test_right_code_unlocks_and_start_works`; `test_changed_code_stops_unstarted_but_not_running` (Review Focus 3); `test_removed_code_opens_run`; `test_eleventh_wrong_code_in_a_minute_is_429` and `test_limit_resets_after_a_minute`; `test_client_ip_prefers_forwarded_for`; `test_qr_and_link_have_no_code`; `test_walkthrough_and_result_link_need_no_code`; `test_test_link_needs_no_code`; `test_one_click_open_has_no_code`; `test_new_code_shown_once` (second GET of the run page does not contain it).
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_access_codes.py tests/api/test_access_code_flow.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(participants): access code per run`.

### Task 6: Attempts table, test links, preview, logs

**Files:**
- Modify: `app/domain/participants.py`, `app/api/admin_runs.py` (`_run_context`), `admin/run.html`, `app/domain/preview.py` or `app/api/admin_preview.py` (fields shown, ignored), `app/domain/run_links.py` (participants deleted with attempts)
- Test: `tests/api/test_run_attempts_table.py`, `tests/domain/test_test_links.py`, `tests/integration/test_no_personal_data_in_logs.py`

**Interfaces:**
- `participants.AttemptRow(name: str, email: str | None, score: Decimal | None, max_score: Decimal | None, submitted_at: datetime)`; `participants.attempt_rows(run: QuizRun) -> list[AttemptRow]`: `FINISHED` attempts by `submitted_at`. The unsent count stays as in C1.
- `run_links.delete_attempts` and `delete` remove the run's `Participant` rows after its attempts.

- [ ] **Step 1: Tests** (`AC-75`): `test_table_shows_name_email_score_time`; `test_table_lists_only_finished`; `test_empty_name_shows_bez_jmena`; `test_email_absent_from_public_pages` (quiz, result, walkthrough HTML do not contain it); `test_table_needs_login`; `test_test_link_has_fields_but_no_repeat_limit`; `test_deleting_test_link_removes_participants`; `test_preview_shows_fields_and_stores_nothing`; `test_no_log_line_contains_name_or_email` (`caplog` at DEBUG through start, submit with a refused duplicate, fill-in later, admin table).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(participants): attempts table, test links and preview`.

### Task 7: Translations, documents, final checks

**Files:**
- `app/locale/*` via `make messages` (cs, en, uk for every new string)
- `docs/_architecture/adr/0049-participants-and-access-code.md`, `adr/README.md`
- `docs/_architecture/acceptance-criteria.md` (AC-70 to AC-76 as used in the tests above)
- `docs/privacy.md` (`FR-32` "when to ask" is a choice, default at the end; names and e-mails are kept until retention arrives in D3; the two cookies)
- `docs/_architecture/plugins/participants.md`, `security.md` (code storage, limit, IP source), `data-model.md`, `modules/domain.md` (`ABANDONED`), `modules/api-ui.md` (addresses and "Where things are set"), `roadmap.md` (C2 Done), `CLAUDE.md` (milestones, Stav, "Další je C3"), `app/*/CLAUDE.md` touched, `.claude/skills/kvizotron-check-integration/flows.md` (code → start → identity → submit → table)
- Remove the stale "until C1" comment at `ATTEMPT_LIFETIME`.

ADR-0049 records: cookie only on need, a separate unlock cookie, the hash bound to the run id, the code per run without inheritance, "when to ask" as a setting, `ABANDONED` for "counts only when submitted", the client IP source.

- [ ] **Step 1:** `make messages`, then fill every empty `msgstr` in cs and uk; run `make messages` again.
- [ ] **Step 2:** Write the documents above.
- [ ] **Step 3: Run** `make quality`. Expected: PASS (lint, tests, gitleaks, tech-debt check, `tests/test_docs.py` naming AC-70 to AC-76).
- [ ] **Step 4: Run** `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke`. Expected: PASS; additionally the code limit counts by client IP through Caddy (one request with a wrong code, `X-Forwarded-For` arriving at the app is the client's).
- [ ] **Step 5: Commit** `docs: C2 participants`.
- [ ] **Step 6:** Verification by `kvizotron-milestone` step 3: walkthrough on a new quiz in `kvizotron-browser` (spec Verification list), `kvizotron-check-applied`, final review.

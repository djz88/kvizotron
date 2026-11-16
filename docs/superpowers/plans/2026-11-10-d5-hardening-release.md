# D5 Hardening & release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-address limits on login, submit and start, HSTS and header review, daily verified backup with manual restore, a 50-participant load test, a cleaner acceptance list, one configuration reference, and v1.0.0.

**Architecture:** Limits are one thread-safe in-memory module in `app/api` replacing `code_limit.py`. Backup and restore are a domain service plus two management commands next to `jobs`; the `jobs` loop makes one backup per local day into a new `backups` volume. The load test is a stdlib script against the Docker stack plus a thread pytest on a file SQLite database.

**Tech Stack:** Django, gunicorn (1 worker, 8 threads), SQLite WAL, Caddy, Docker Compose, pytest, `sqlite3.Connection.backup`.

**Spec:** `docs/superpowers/specs/2026-11-10-d5-hardening-release-design.md`

## Global Constraints

- One milestone, one branch `feat/d5-hardening-release` in `.worktrees/`, one squash commit into main after consent. Commit only named paths; never stage root files (logos, `report.md`, `.superpowers/`).
- Defaults: login 5/min per login name + address (failed only); code 10/min per address (failed only, `KVZ_CODE_ATTEMPTS_PER_MINUTE`); submit 120/min per address (`KVZ_SUBMITS_PER_MINUTE`); start 300/min per address (`KVZ_STARTS_PER_MINUTE`); login variable `KVZ_LOGIN_ATTEMPTS_PER_MINUTE`. Window 60 s sliding. Refusal is 429 with `Retry-After: 60`.
- 50 clients behind one address never get 429 at defaults.
- HSTS: `Strict-Transport-Security: max-age=15552000`, no `includeSubDomains`, no `preload`.
- Backups: `KVZ_BACKUP_PATH` (default `/data/backups`), `KVZ_BACKUP_RETENTION_DAYS` default 30, integer >= 1; one backup per local day; SQLite backup API only, never a file copy; restored files owned by uid 1000.
- UI says "run"/"běh", never "round"/"kolo". Admin texts cs/en, public texts cs/en/uk; `make messages` after text changes. Docs in `docs/` English. No personal data, answers, codes or secrets in logs of new code; log exception types only.
- Do not touch the data or global settings of the `kvizotron-browser` stack; new quiz prefix `d5`.
- Every behaviour change has a test written first and seen failing. Existing tests are never weakened.
- New AC start at AC-129; each is named by a test (`tests/test_docs.py`).
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A client address missing or empty (`REMOTE_ADDR` blank, `X-Forwarded-For` with spaces or several values): limits must not crash and must not put everybody in one bucket silently. Test in Task 1.
- Login name with different case or surrounding spaces: `Alice` and `alice ` must share one bucket. Test in Task 2.
- A refused start must create no `Participant` row and no cookie. Test in Task 3.
- A backup made while a writer holds the lock, or interrupted halfway (power loss, kill): never leaves a directory that `restore latest` would pick. Test in Task 6.
- Restore of a backup from an older schema (fewer migrations) must be refused or migrated explicitly, never half-applied. Test in Task 7.
- Retention pruning must never delete the only valid backup, even with a clock set far ahead. Test in Task 6.
- Media filename collisions on hard link: a replaced file with the same storage key must be copied, not linked. Test in Task 6.

---

## File Structure

- Create `app/api/rate_limit.py` (replaces `app/api/code_limit.py`), `app/domain/backup.py`, `app/domain/management/commands/backup.py`, `app/domain/management/commands/restore.py`, `tools/load_participants.py`, `docs/configuration.md`, two ADRs.
- Modify `app/settings.py`, `app/api/play.py`, `app/api/admin_auth.py`, `app/domain/management/commands/jobs.py`, `deploy/compose.yaml`, `deploy/Caddyfile`, `deploy/smoke.sh`, `Dockerfile`, `Makefile`, `tests/test_docs.py`, docs listed in Task 13.
- Tests: `tests/api/test_rate_limit.py`, `tests/api/test_login_limit.py`, `tests/api/test_play_limits.py`, `tests/api/test_security_headers.py`, `tests/domain/test_backup.py`, `tests/domain/test_restore.py`, `tests/domain/test_jobs_backup.py`, `tests/integration/test_concurrent_submissions.py`, `tests/test_configuration_docs.py`.

---

### Task 1: Rate-limit module replacing `code_limit`

**Files:**
- Create: `app/api/rate_limit.py`
- Delete: `app/api/code_limit.py`
- Modify: `app/settings.py:44`, `app/api/play.py:23,402-413`, `tests/api/test_access_code_flow.py:7,19-21,104-132`, `app/api/CLAUDE.md`
- Test: `tests/api/test_rate_limit.py`

**Interfaces:**
- Produces:
  - `client_ip(request: HttpRequest) -> str` (same rule as today: first `X-Forwarded-For` value, else `REMOTE_ADDR`; a blank result becomes `"unknown"`).
  - `allow(bucket: str, key: str, now: float) -> bool` (true while fewer than the bucket's limit are recorded in the last 60 s).
  - `record(bucket: str, key: str, now: float) -> None`.
  - `retry_after() -> str` returning `"60"`.
  - `sweep(now: float)`, `tracked() -> int`, `reset() -> None`.
  - `BUCKETS = ("login", "code", "submit", "start")`; the limit of a bucket is read from `settings` at call time: `KVZ_LOGIN_ATTEMPTS_PER_MINUTE`, `KVZ_CODE_ATTEMPTS_PER_MINUTE`, `KVZ_SUBMITS_PER_MINUTE`, `KVZ_STARTS_PER_MINUTE`.
  - An unknown bucket name raises `KeyError`.

- [ ] **Step 1: Failing tests in `tests/api/test_rate_limit.py`**: `test_a_bucket_allows_up_to_its_limit_then_refuses` (limit 3 via `settings` fixture: 3 `record`s, `allow` false at `now+30`, true at `now+61`), `test_buckets_and_keys_are_independent`, `test_client_ip_takes_the_first_forwarded_value_and_strips_spaces`, `test_a_blank_address_becomes_unknown_and_does_not_raise`, `test_idle_keys_are_swept_past_1000_tracked`, `test_it_holds_under_50_threads` (50 threads each `record` 2 times on one key; `tracked() == 1`, final count exactly 100 via `allow` flipping at limit 100), `test_defaults` (asserts the four numbers from Global Constraints).
- [ ] **Step 2: Run** `uv run pytest tests/api/test_rate_limit.py -q`. Expected: FAIL, module missing.
- [ ] **Step 3: Implement `app/api/rate_limit.py`** from the body of `code_limit.py` (keyed dict of timestamp lists, one `threading.Lock`, sweep threshold 1000), with the bucket as part of the dict key. In `app/settings.py` add the three new `_positive_int` settings next to the existing one.
- [ ] **Step 4: Migrate callers.** In `play.py` replace `code_limit.allow(ip, now)` with `rate_limit.allow("code", ip, now)`, `code_limit.failed(ip, now)` with `rate_limit.record("code", ip, now)`, `Retry-After` with `rate_limit.retry_after()`. In `test_access_code_flow.py` change only imports and call syntax; the asserted values stay the same. Delete `code_limit.py`; update the line in `app/api/CLAUDE.md`.
- [ ] **Step 5: Run** `uv run pytest tests/api -q`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(limits): one in-memory limiter with four buckets`.

### Task 2: Login limit

**Files:** Modify `app/api/admin_auth.py:42-60`; Test `tests/api/test_login_limit.py`; texts via `make messages`.

**Interfaces:**
- Consumes: `rate_limit.allow/record/client_ip/retry_after` (Task 1).
- Produces: login key is `f"{login.strip().lower()}|{ip}"` in bucket `"login"`.

- [ ] **Step 1: Failing tests:**
  - `test_the_sixth_wrong_login_in_a_minute_is_refused` (5 wrong POSTs get 200 with the existing wrong-login message; the 6th gets 429, `Retry-After == "60"`, and the page still renders the form with a message).
  - `test_a_correct_login_is_refused_while_the_bucket_is_full_but_counts_nothing` (documents the chosen rule: after 5 failures even the right password gets 429 until the window passes).
  - `test_failures_of_another_address_do_not_lock_this_one` (same login, different `X-Forwarded-For` still logs in).
  - `test_case_and_spaces_share_one_bucket` (`Alice`, `alice `, `ALICE` count together).
  - `test_a_successful_login_is_not_counted`.
  - `test_the_message_is_translated` (cs and en).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** the check before `authenticate` and `record` after a failed one in `login_page`; the 429 response reuses the login template with an extra error text "Too many attempts. Please try again in a minute." and `Retry-After`. Run `make messages` and fill the cs msgstr.
- [ ] **Step 4: Run** `uv run pytest tests/api/test_login_limit.py tests/api/test_admin_auth.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(limits): limit failed admin logins per name and address`.

### Task 3: Submit and start limits

**Files:** Modify `app/api/play.py` (`start` at 276, `submit` at 659, `MESSAGES` and `STATUS` tables near line 100-130); Test `tests/api/test_play_limits.py`; texts via `make messages`.

**Interfaces:**
- Consumes: `rate_limit.*` (Task 1).
- Produces: error code `"rate_limited"` in `MESSAGES` (cs/en/uk text "Too many requests from this address. Please try again in a minute.") and `STATUS["rate_limited"] = 429`; the response carries `Retry-After: 60`. `start` counts bucket `"start"`, `submit` counts bucket `"submit"`, both keyed by `client_ip`, checked first, before any lookup or row creation, and recorded for every request.

- [ ] **Step 1: Failing tests:**
  - `test_start_is_refused_after_the_limit_without_creating_a_participant` (limit 3 via `settings`; 4th POST: 429, `Participant.objects.count() == 3`, no `Set-Cookie`).
  - `test_submit_is_refused_after_the_limit` (limit 2).
  - `test_50_clients_behind_one_address_start_and_submit_at_defaults` (50 starts and 50 submits from one `X-Forwarded-For`, none 429).
  - `test_another_address_is_not_affected`.
  - `test_the_refusal_is_a_fragment_for_htmx_and_a_page_otherwise`.
  - `test_the_refusal_is_translated_in_cs_en_uk`.
  - `test_check_and_resume_and_time_are_not_limited` (pins the audit rule from the spec: 200 requests of each pass).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** a small helper `_limited(request, bucket, locale_default) -> HttpResponse | None` in `play.py` returning the 429 response (locale from `request.locale`) or `None`; call it at the top of `start` and `submit`. Run `make messages`, fill cs and uk msgstr.
- [ ] **Step 4: Run** `uv run pytest tests/api -q`. Expected: PASS, including all existing play tests.
- [ ] **Step 5: Commit** `feat(limits): limit starting and submitting per address (closes TD-029)`; resolve TD-029 with `make tech-debt-resolve id=TD-029` in the same commit.

### Task 4: Route audit

**Files:** Modify `tests/api/test_request_limits.py`; `docs/_architecture/security.md`.

**Interfaces:** Produces the table `LIMITS_OF_ROUTES: dict[str, str]` in the test: every public URL name (from `app/api/urls.py` including module routes under `/m/`) mapped to `"login" | "code" | "submit" | "start"` or `"unlimited: <reason>"`.

- [ ] **Step 1: Failing test** `test_every_public_route_has_a_declared_limit` walks `get_resolver().url_patterns`, collects each non-admin route that accepts POST (inspect the view's `require_POST` or send a probe), and asserts it is a key of `LIMITS_OF_ROUTES`; a second test asserts every `LIMITS_OF_ROUTES` key still exists.
- [ ] **Step 2: Run, expect FAIL** (table empty).
- [ ] **Step 3: Fill the table** by reading each route: `start`→start, `submit`→submit, `run_code`→code, and for `resume`, `check`, `attempt_time`, `switch`, `revision_status`, `result_identity`, `test_link`, `result`, module routes: decide from what it writes. Any route that creates a row or writes a file without a bucket gets the closest bucket (state it in the commit message); the rest get a reason. Add the table, as a short list, to `security.md` under the rate-limit text, replacing "Rate limits on upload wait for D5".
- [ ] **Step 4: Run** `uv run pytest tests/api/test_request_limits.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `test(limits): every public route declares its limit`.

### Task 5: HSTS and response headers

**Files:** Modify `deploy/Caddyfile`, `deploy/smoke.sh`, `app/settings.py` as needed; Test `tests/api/test_security_headers.py`, `tests/test_deploy_headers.py`.

**Interfaces:** Produces the header set asserted for a public page, an admin page, a 404, `/media/<id>` and `/assets/<name>`: `X-Content-Type-Options: nosniff`, a `Referrer-Policy` value, a frame restriction (`X-Frame-Options: DENY` or CSP `frame-ancestors 'none'`), CSP present, `Cache-Control: private, no-store` on pages carrying private data (result link, identity), session and CSRF cookies `Secure`, `HttpOnly` (session), `SameSite=Lax`.

- [ ] **Step 1: Failing tests.** In `tests/api/test_security_headers.py`, one parametrized test over the routes above asserting the set; record in a comment which headers Django already sends, so a reader sees what was checked. In `tests/test_deploy_headers.py` read `deploy/Caddyfile` as text (like `tests/test_deploy_time_zone.py`) and assert one `Strict-Transport-Security` header with `max-age=15552000` and neither `includeSubDomains` nor `preload`.
- [ ] **Step 2: Run, expect FAIL** for at least HSTS; add to the Django side only headers the first run shows missing.
- [ ] **Step 3: Implement** `header Strict-Transport-Security "max-age=15552000"` in the site block of `deploy/Caddyfile`; missing Django headers through the standard `SECURE_*` / `X_FRAME_OPTIONS` settings. Add to `deploy/smoke.sh` a `check "HSTS header" ...` from `curl -skI` over HTTPS.
- [ ] **Step 4: Run** `uv run pytest tests/api/test_security_headers.py tests/test_deploy_headers.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(security): HSTS and a tested set of response headers`.

### Task 6: Backup service

**Files:** Create `app/domain/backup.py`, `app/domain/management/commands/backup.py`; Modify `app/settings.py`; Test `tests/domain/test_backup.py`.

**Interfaces:**
- Produces in `app/domain/backup.py`:
  - `class BackupError(Exception)`.
  - `create(now: datetime) -> Path`: builds `<KVZ_BACKUP_PATH>/.tmp-<date>` then renames to `<date>` (`YYYY-MM-DD`, local date from `app.domain.clock`), returns the final directory; raises `BackupError` and removes the temporary directory on any failure.
  - `verify(directory: Path) -> None`: raises `BackupError` for a missing manifest, a checksum mismatch, a failed `PRAGMA integrity_check`, or migrations in the copy unknown to the installed code.
  - `prune(now: datetime, days: int) -> list[Path]`: deletes valid backups and `pre-restore*` directories older than `days`, never the newest valid one.
  - `listing() -> list[Path]` of complete backups, newest first (ignores `.tmp-*`).
  - `due(now: datetime) -> bool`: no complete backup for today's local date.
- Settings: `KVZ_BACKUP_PATH` (default `/data/backups`), `KVZ_BACKUP_RETENTION_DAYS` (positive int, 30).
- Manifest `manifest.json`: `{"created": iso, "schema": [migration names], "files": {"db.sqlite3": {"size", "sha256"}, "media/<storage_key>": {...}}}`.
- Management command `backup`: calls `create`, `prune`, prints the directory and file count.

- [ ] **Step 1: Failing tests** (file SQLite database, temp `KVZ_BACKUP_PATH` and `KVZ_MEDIA_PATH` via `settings`; use `transactional_db`): `test_a_backup_has_a_database_copy_media_and_a_manifest`, `test_the_copy_is_a_consistent_database` (open it, `PRAGMA integrity_check` is `ok`, row counts match), `test_a_backup_is_taken_while_another_thread_writes`, `test_unchanged_media_are_hard_linked_and_changed_ones_copied` (same storage key with different content is copied; compare inodes), `test_a_failure_leaves_no_complete_directory` (monkeypatch the copy step to raise; no `<date>` directory, previous backups intact), `test_a_killed_backup_is_ignored` (a stray `.tmp-*` is not listed), `test_verify_refuses_a_changed_file`, `test_verify_refuses_unknown_migrations`, `test_prune_deletes_old_ones_by_days`, `test_prune_keeps_the_newest_valid_backup_whatever_the_clock`, `test_due_is_true_once_per_local_date`, `test_errors_are_logged_by_type_only` (caplog contains the exception class name and no path or value).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Database copy with `sqlite3.connect(NAME).backup(target, pages=100)` (small page steps so a writer is not starved); media by walking `KVZ_MEDIA_PATH`, linking when the previous backup holds a file of the same relative path and same sha256, else `shutil.copy2`, with copy as the fallback when `os.link` raises `OSError`. Checksums via `hashlib.sha256`. Verify runs inside `create` before the rename.
- [ ] **Step 4: Run** `uv run pytest tests/domain/test_backup.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(backup): verified daily backup of database and media`.

### Task 7: Restore command

**Files:** Create `app/domain/management/commands/restore.py`; Modify `app/domain/backup.py`; Test `tests/domain/test_restore.py`.

**Interfaces:**
- Consumes: `backup.verify`, `backup.listing` (Task 6).
- Produces `backup.restore(directory: Path, now: datetime) -> RestoreReport` (`@dataclass`: `database_bytes: int`, `media_files: int`, `previous: Path`) and command `manage.py restore <YYYY-MM-DD|latest>`. Steps: verify the backup; refuse if `BEGIN EXCLUSIVE` on the live database fails; move the current database files (`-wal`, `-shm` too) and media contents into `<KVZ_BACKUP_PATH>/pre-restore-<timestamp>/`; copy the backup in; `chown` to uid 1000 where the process may (skip only if not permitted, and print a warning); check migrations; print counts. Never touches the volume roots. On a failure after the move, move the previous data back.

- [ ] **Step 1: Failing tests:** `test_restore_brings_back_the_rows_and_media_of_the_backup` (create backup, change data, restore, compare), `test_restore_keeps_the_previous_data_in_pre-restore`, `test_restore_refuses_a_corrupted_backup_and_changes_nothing`, `test_restore_refuses_while_the_database_is_locked`, `test_restore_refuses_a_backup_from_an_older_schema`, `test_a_failure_halfway_puts_the_previous_data_back`, `test_restored_files_are_owned_by_the_data_owner` (compare to the owner of the backup root's parent; the 1000 case is checked in smoke, Task 8), `test_latest_picks_the_newest_complete_backup`, `test_unknown_date_is_a_clear_error`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `restore` and the command (`CommandError` with a short message, no paths of user data).
- [ ] **Step 4: Run** `uv run pytest tests/domain/test_restore.py tests/domain/test_backup.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(backup): manual restore with verification and a way back`.

### Task 8: Daily backup in `jobs`, volume and deployment

**Files:** Modify `app/domain/management/commands/jobs.py`, `deploy/compose.yaml`, `Dockerfile:24`, `deploy/smoke.sh`; Test `tests/domain/test_jobs_backup.py`, existing `tests/test_deploy_*.py` style test for compose.

**Interfaces:**
- Consumes: `backup.due`, `backup.create`, `backup.prune`.
- Produces: `run_loop(stop, wait, one_pass)` keeps its signature; the callable passed in by `Command.handle` becomes `jobs.pass_once()` that runs `retention.run_pass()` and then, if `backup.due(now)`, `create` + `prune`, each in its own `try` so a backup failure never stops retention and vice versa. A volume `backups` mounted at `/data/backups` in `jobs` only; the Dockerfile creates `/data/backups` owned by `kvizotron`.

- [ ] **Step 1: Failing tests:** `test_one_pass_runs_retention_and_a_due_backup`, `test_no_second_backup_on_the_same_date`, `test_a_failing_backup_does_not_stop_the_retention_pass_and_is_logged_by_type`, `test_compose_mounts_backups_in_jobs_only` (parse `deploy/compose.yaml`), `test_dockerfile_creates_the_backup_directory`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Smoke additions: after `up`, `compose exec -T jobs ls /data/backups` shows one dated directory, `compose exec -T jobs id -u` is 1000, `app` has no `/data/backups`, and `compose run --rm --no-deps jobs python manage.py restore latest` after `compose stop jobs app` leaves `ls -n` owners of the database file at 1000, then `compose start app jobs` and `/healthz` answers.
- [ ] **Step 4: Run** `uv run pytest tests/domain/test_jobs_backup.py tests/test_deploy_time_zone.py -q` and `make smoke` (with the ports from CLAUDE.md while `kvizotron-browser` runs). Expected: PASS.
- [ ] **Step 5: Commit** `feat(backup): daily backup in the jobs service and a backups volume`.

### Task 9: Concurrency pytest (50 threads)

**Files:** Test `tests/integration/test_concurrent_submissions.py`; a fixture file database in `tests/integration/conftest.py` if none exists.

**Interfaces:** Consumes the real `start` and `submit` views through `django.test.Client` per thread.

- [ ] **Step 1: Write the test** `test_50_participants_submit_at_once_with_photos`: a file SQLite database in WAL with the production `OPTIONS` (`IMMEDIATE`, timeout 20), a quiz with a choice question and a photo question, 50 threads behind a `threading.Barrier`, one address; each submits once with a tiny valid JPEG. Assert: all 200; exactly 50 submitted `Attempt` rows; exactly one `Attempt` per `submission_key`; a second POST with the same key from 5 of them creates nothing new and returns the same result; photo `Asset` rows equal 50; no `OperationalError` in any thread; no 429.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_concurrent_submissions.py -q`. If it fails, the failure is the finding: fix the cause in the domain (never raise the timeout or add a retry to hide it) and keep the test.
- [ ] **Step 3: Commit** `test(load): 50 concurrent submissions with photos on a file database`.

### Task 10: Load script, `make load`, address probe

**Files:** Create `tools/load_participants.py`; Modify `Makefile`, `tools/CLAUDE.md`; Test `tests/test_makefile.py` (target exists and is in `.PHONY`).

**Interfaces:** `python -m tools.load_participants --base URL --run RUN_ID [--clients 50] [--photo-kb 700]` prints one line per criterion `PASS`/`FAIL` and exits non-zero on any `FAIL`. `make load` starts a stack under project `kvizotron-load` (the way `deploy/smoke.sh` does, with its own secret and ports `LOAD_HTTP_PORT`/`LOAD_HTTPS_PORT`), creates the quiz and run through `compose exec -T app python manage.py shell`, runs the script, runs `backup` during the submissions in one pass, restores into a second fresh project and compares counts and checksums, then removes only its own projects.

- [ ] **Step 1: Failing test** in `tests/test_makefile.py`: `load` is a documented target.
- [ ] **Step 2: Implement** the script: stdlib only; 50 starts then a barrier, then 50 simultaneous submits with a generated JPEG of the given size, in the question-per-page mode with reveal (call `check` before each submit as the page script does). Criteria: no non-2xx, 50 submitted attempts exactly once each (read through `compose exec … manage.py shell`), repeat submission with the same key creates nothing, every photo stored once, no `database is locked` in `compose logs app`, slowest answer under 5 s, counts and checksums equal after restore, and the **address probe**: start a probe stack with `KVZ_STARTS_PER_MINUTE=3`, send 4 starts from the host's LAN address (`hostname -I` first value) and 1 from `127.0.0.2`; the probe passes when the application counts them per source (4th from LAN refused, the one from `127.0.0.2` accepted). A failing probe prints what to change and exits non-zero. Also print the number of queries of one public page (use `KVZ_DEBUG` off; count via the test client in the pytest of Task 9 instead if the stack cannot report it, and say so).
- [ ] **Step 3: Run** `make load`; keep the output for the closing report. If the probe fails, make the smallest fix in `deploy/compose.yaml` or `Caddyfile`; if the fix is a design change, stop and ask the user.
- [ ] **Step 4: Commit** `feat(load): 50-participant load test with backup, restore and address probe`.

### Task 11: Acceptance list

**Files:** Modify `tests/test_docs.py` (`AC_NOT_NAMED_BY_A_TEST`, `LAST_EXCUSED`), test files that cover each AC.

**Interfaces:** the set only shrinks. Each AC removed is named in a test's docstring or name (`AC-NN`).

- [ ] **Step 1: List.** For each of AC-03, 04, 05, 06, 08, 09, 10, 11, 12, 14, 15, 16, 17, 18 read its row in `acceptance-criteria.md`, find the existing test that proves it (search the test tree by topic), and write the pairing into a scratch note in `$CLAUDE_JOB_DIR/tmp`.
- [ ] **Step 2: Name or write.** Add the AC id to the covering test's docstring; where nothing covers a clause, write the missing test first (failing, then passing). AC-15 is named by Tasks 9 and 10 tests. A criterion only a person can check stays in the set with a one-line comment.
- [ ] **Step 3: Shrink** the set; run `uv run pytest tests/test_docs.py -q`. Expected: PASS.
- [ ] **Step 4: Commit** `test(acceptance): name the tests behind AC-03 to AC-18`.

### Task 12: Configuration reference

**Files:** Create `docs/configuration.md`; Modify `docs/deployment.md:33-45`, `deploy/.env.example`; Test `tests/test_configuration_docs.py`.

- [ ] **Step 1: Failing test** `test_every_kvz_variable_is_documented`: collect `KVZ_[A-Z_]+` from `app/`, `deploy/compose.yaml`, `deploy/Caddyfile`, `Dockerfile`, excluding `KVZ_MODULES`/`KVZ_PERSISTENCE` (Python names, not variables) and the `KVZ_PROVIDER_` prefix; assert each appears in a table row of `docs/configuration.md`; and `test_deployment_does_not_repeat_the_table` (no `| `KVZ_` rows left in `deployment.md`).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Write `docs/configuration.md`** (English): one table of variables (required, default, meaning, where read) including the five new ones and the three ports/time zone, a section "Where the settings live" pointing to the global/quiz/question scopes of ADR-0042 and the admin pages, and one line on limits' memory-only behaviour. Replace the table in `deployment.md` with a link; add the new variables to `deploy/.env.example`.
- [ ] **Step 4: Run** `uv run pytest tests/test_configuration_docs.py tests/test_docs.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `docs: one configuration reference`.

### Task 13: Milestone documents and ADRs

**Files:** see the milestone skill, section 4.

- [ ] **Step 1: ADRs** `0058-rate-limit-buckets.md` (refines ADR-0030: login failed-only keyed by name + address, start bucket, submit per attempt, 429 behaviour, route audit) and `0059-backup-and-restore.md` (daily, jobs, volume, hard links, verify before commit, restore refuses and keeps `pre-restore`, operator note on erasure); add `Refined by` to ADR-0030 and both rows to `adr/README.md`.
- [ ] **Step 2: Documents.** `roadmap.md` D5 row `Done 2026-…`; `acceptance-criteria.md` AC-129 and following (limits, HSTS and headers, backup made and verified, restore verified with ownership, backup retention, 50 participants); `security.md`, `privacy.md` (remove "Backup retention is a matter for D5", describe the mechanism), `deployment.md` (backup and restore procedure, restore drill, off-machine copy, HSTS note, release checks with commands), `architecture.md:47`, `modules/api-ui.md`, `data-model.md` (none changed: state "no tables"), `open-questions.md`, `TECH_DEBT.md` (TD-029 resolved; defer anything found via `make tech-debt-create title="…"` with Where/Effect/Solution), `.claude/skills/kvizotron-check-integration/flows.md` (limit, backup and restore flows), `CLAUDE.md` root (milestone list, Stav, "Další je …": nothing left before v1.0 except the TD triage the user postponed), `app/api/CLAUDE.md`, `app/domain/CLAUDE.md`, `tools/CLAUDE.md`, `ADR-0044`/`0047` "until D5" lines.
- [ ] **Step 3: Run** `uv run pytest tests/test_docs.py tests/test_wiring.py -q`. Expected: PASS.
- [ ] **Step 4: Commit** `docs: close milestone D5`.

### Task 14: Verification, version and handover

- [ ] **Step 1:** `make quality`; show the pass counts.
- [ ] **Step 2:** `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke`.
- [ ] **Step 3:** `make load`; keep the output.
- [ ] **Step 4:** Skill `kvizotron-browser-walkthrough` on a new quiz `d5-…`: login 429 message cs/en, the start refusal on a public page in cs/en/uk, the Modules page, and the footer; stack `kvizotron-browser` only through the skill.
- [ ] **Step 5:** Skill `kvizotron-check-applied`; fix gaps with a test first.
- [ ] **Step 6:** One fresh reviewer for the whole branch with the outputs above; fix Critical and Important findings with a failing test first.
- [ ] **Step 7:** If every AC with Stage D and AC-01 to AC-18 is green, set `version = "1.0.0"` in `pyproject.toml` and refresh `uv.lock` with `uv lock`; commit `chore: version 1.0.0`.
- [ ] **Step 8:** Report decisions made for the user and deferred items in full, then offer the options of `superpowers:finishing-a-development-branch`. Merge, push, tag and branch deletion wait for consent; check `git log`, `git status` and reflog of main first.

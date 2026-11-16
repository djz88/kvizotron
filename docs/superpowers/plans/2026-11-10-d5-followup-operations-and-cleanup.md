# D5 follow-up 2: operations and cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `jobs` loop visible, make restore refuse beside a live `app` or `jobs` and mark an interrupted restore, make a backup that leaves old backups behind fail, and close the small leaks TD-021, TD-015 and TD-076 with the related TD-072, TD-074, TD-075 and a TD-086 measurement.

**Architecture:** One stdlib-only module `app/domain/heartbeat.py` writes heartbeat files and a pass record beside the database file. `jobs` and a small `app` middleware write them; `restore` reads them; the `jobs` healthcheck and the Deletion history page read the pass record. The restore marker lives in the stash directory. `Participant.email_key` makes the erasure search one query.

**Tech Stack:** Django, SQLite (WAL), Jinja2, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-10-d5-followup-operations-and-cleanup-design.md` (the spec is the authority; where a task is silent, the spec decides).

## Global Constraints

- Branch `feat/d5-followup-operations` in a worktree made with `make worktree-create feat/d5-followup-operations`; never work on `main`.
- Every behaviour change starts with a failing test; tests are never weakened or deleted to pass.
- Logs carry counts and exception types only, never a path, value, address, answer or name (`backup.py` convention).
- No new setting or environment variable (`tests/test_configuration_docs.py` stays green). Stale limit of both heartbeats **60 s**; `jobs` writes every **15 s**; `app` writes at most once per **10 s**.
- Admin texts cs/en only; "run", never "round"; run `make messages` once, at the end (Task 12), and commit only the catalogs that changed.
- Acceptance criteria: AC-143 (restore refuses beside a live `app`/`jobs` and an interrupted restore is marked), AC-144 (the `jobs` pass is visible: record, healthcheck, history page), AC-145 (a prune that leaves backups makes `backup` fail), AC-146 (erasure search by `email_key`, board cache cleared), AC-147 (no orphan photo files, a bad photo address logs nothing). A test must name each id in its docstring (`tests/test_docs.py`).
- Do not read, edit or commit `deploy/.env.example`, the logo files, `.superpowers/` or `.playwright-mcp/`. Do not touch the data or global settings of the `kvizotron-browser` stack; walkthrough quiz prefix `d7`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A restore that crashes after the marker, then a second restore: refused naming the right directory, never the incomplete stash of a crash during the copy.
- `prune` with a marked `pre-restore` older than the retention: it stays.
- A heartbeat file left by a crash 61 seconds ago does not block restore; one left 30 seconds ago does, with the seconds to wait in the message.
- `search_email` with mixed case, surrounding spaces, `ß`/`ss`-style casefold, and an address stored before the migration.
- A failure of the second of three photos in one submission leaves no file on the media volume.
- A heartbeat write into a read-only or missing directory never breaks a request or the `jobs` loop.

---

### Task 1: Heartbeat module

**Files:**
- Create: `app/domain/heartbeat.py`
- Test: `tests/domain/test_heartbeat.py`

**Interfaces:**
- Produces (used by Tasks 2, 3, 4, 6):
  - `STALE_SECONDS = 60`, `JOBS_INTERVAL = 15`, `APP_INTERVAL = 10`
  - `directory() -> Path | None`: parent of the configured database file; `None` for `:memory:` or an unusable path.
  - `beat(name: str, directory: Path | None = None) -> None`: writes or touches the heartbeat of `name` (`"app"` or `"jobs"`); never raises.
  - `age(name: str, directory: Path, now: float | None = None) -> float | None`: seconds since the last beat, `None` when there is no file.
  - `clear(name: str, directory: Path | None = None) -> None`: removes it; never raises.
  - `PassRecord` (frozen dataclass: `started: datetime | None`, `finished: datetime | None`, `outcome: str | None`); `write_pass(started: datetime, finished: datetime | None, outcome: str | None, directory: Path | None = None) -> None`; `read_pass(directory: Path | None = None) -> PassRecord | None`.
  - `jobs_healthy(now: datetime, directory: Path | None = None) -> bool`: false when the last finish is older than 7200 s, or there is no finish and the start is older than 3600 s; true when there is no record at all and when nothing can be read.
  - `python -m app.domain.heartbeat check` (a `__main__` guard): exits 0 when `jobs_healthy`, 1 otherwise; it opens no database and no network.
- Consumes: `django.conf.settings.DATABASES["default"]["NAME"]`.

- [ ] **Step 1: Failing tests** in `tests/domain/test_heartbeat.py` (use `tmp_path`): `beat` then `age` is below 1 s; `age` of a missing name is `None`; `clear` removes it and a second `clear` is silent; `beat` into a missing directory and into a read-only one does not raise; `directory()` is `None` for an in-memory database; pass record round-trips started, finished and outcome, and an unfinished record keeps `finished=None`; `jobs_healthy` is true at 7199 s since finish and false at 7201 s, true for 3599 s since start with no finish and false at 3601 s, true with no record.
- [ ] **Step 2: Run, expect FAIL** (`make test` on the file, or `uv run pytest tests/domain/test_heartbeat.py -q`).
- [ ] **Step 3: Implement** the module. File names are the builder's choice (one hidden file per name and one record file in the directory). The pass record is written atomically (write a temporary file, then `os.replace`). The reading functions use only the standard library; the settings import stays inside `directory()`.
- [ ] **Step 4: Run, expect PASS**; `make lint`.
- [ ] **Step 5: Commit** `feat(jobs): heartbeat files and the pass record`.

---

### Task 2: `jobs` writes the heartbeat and the pass record

**Files:**
- Modify: `app/domain/management/commands/jobs.py`
- Test: `tests/domain/test_jobs_backup.py` (extend) or a new `tests/domain/test_jobs_heartbeat.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `pass_once()` returns normally as now but records the pass; `run_loop` and `Command.handle` unchanged in signature.

- [ ] **Step 1: Failing tests** (AC-144): a successful `pass_once` leaves a record with `started`, `finished` and outcome `ok`; a `pass_once` where `retention.run_pass` raises, and one where `backup.create` raises, leave outcome `failed` and a finish; while a pass runs (monkeypatch `retention.run_pass` to read the record) the record has `started` and the previous `finished`; `Command.handle` removes the `jobs` heartbeat when the stop event is set (drive `run_loop` and the stop path with a fake wait as the existing tests do); the heartbeat thread beats (use a short interval injected by an argument or a module constant that the test patches).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** `pass_once` writes the record at start and end. `handle` starts a daemon thread that calls `heartbeat.beat("jobs")` every `JOBS_INTERVAL` seconds until the stop event, writes one beat before the first pass, and calls `heartbeat.clear("jobs")` after `run_loop` returns. The failed/ok outcome is `failed` when any of the retention pass, the backup, or the prune raised.
- [ ] **Step 4: Run, expect PASS**; `make lint`.
- [ ] **Step 5: Commit** `feat(jobs): record each pass and beat while running`.

---

### Task 3: `app` heartbeat and restore refuses beside a live `app` or `jobs`

**Files:**
- Create: `app/kernel/middleware.py` addition `HeartbeatMiddleware` (or a new file in `app/api/` if the layers test forbids it; `tests/test_layers.py` decides)
- Modify: `app/settings.py` (`MIDDLEWARE`), `app/domain/backup.py` (`_require_unused`), `deploy/load.sh` (restore drill)
- Test: `tests/domain/test_restore.py` (extend), `tests/api/test_heartbeat_middleware.py` (new)

**Interfaces:**
- Consumes: Task 1.
- Produces: `backup._require_unused(live: Path)` also raises `BackupError` with a fixed message when `heartbeat.age("app", live.parent)` or `heartbeat.age("jobs", live.parent)` is below `STALE_SECONDS`. The message names the service and the whole seconds left until it counts as stopped, and never a path.

- [ ] **Step 1: Failing tests** (AC-143): restore refuses with a young `app` heartbeat beside the live database and with a young `jobs` heartbeat; it accepts one older than 60 s (set the file mtime back) and none; the message holds the service name and a number of seconds and no path; the restore leaves the live data untouched when it refuses. Middleware: a request through the test client creates the `app` heartbeat; a second request within 10 s does not write again (patch `heartbeat.beat`, count calls); `/healthz` counts; a failing `beat` does not change the response.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** The check uses `live.parent`, not the settings, so a restore of any database path looks beside that file. The middleware keeps a per-process monotonic time of the last write and swallows errors; register `atexit` to `clear("app")` once. Add the middleware last in `MIDDLEWARE`. Update the `_require_unused` docstring (TD-089 is now closed by it). In `deploy/load.sh` the restore drill, after `compose stop app jobs`, waits (up to 90 s) until `restore` no longer refuses on heartbeats, by retrying `restore latest` only while its output names a heartbeat refusal.
- [ ] **Step 4: Run, expect PASS** (`tests/domain/test_restore.py`, `tests/api/test_heartbeat_middleware.py`, `tests/test_layers.py`, `tests/test_wiring.py`); `make lint`.
- [ ] **Step 5: Commit** `feat(restore): refuse beside a live app or jobs`.

---

### Task 4: Marker of an interrupted restore

**Files:**
- Modify: `app/domain/backup.py` (`restore`, `prune`)
- Test: `tests/domain/test_restore.py`, `tests/domain/test_backup.py`

**Interfaces:**
- Produces: marker file `.restoring` inside the `pre-restore-<time>` directory; `backup.MARKER = ".restoring"`; `_marked() -> list[Path]` (stash directories that hold it).

- [ ] **Step 1: Failing tests** (AC-143): after `restore` with `_install` patched to raise `KeyboardInterrupt`-like `BaseException` or to kill midway (raise a custom `BaseException` and make `_put_back` raise too), the marker stays in the stash and a second `restore` raises `BackupError` naming that directory's name and no path; a successful restore leaves no marker; a failed restore whose `_put_back` succeeds leaves no marker; a crash inside `_stash` (patch `_copy_file` to raise on the media copy) leaves no marker and no stash directory; `prune` with a marked `pre-restore` directory 400 days old keeps it, and removes an unmarked one of the same age; a stale marker is the only thing that blocks without an age.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** After `_stash` returns (it already syncs the tree) write the marker, `fsync` it and its directory, then run `_install`. Remove the marker after a successful `_install` and after a successful `_put_back`. At the start of `restore`, inside the lock and before `verify`, raise `BackupError` with a fixed message that names the directory and points to the Restore section of `docs/deployment.md`. In `prune`, skip a `pre-restore` directory that holds the marker.
- [ ] **Step 4: Run, expect PASS**; `make lint`.
- [ ] **Step 5: Commit** `feat(restore): mark an interrupted restore and keep what it left`.

---

### Task 5: `prune` says what stayed; `backup` fails then

**Files:**
- Modify: `app/domain/backup.py` (`prune`, `_remove`), `app/domain/management/commands/backup.py`, `app/domain/management/commands/jobs.py`
- Test: `tests/domain/test_backup.py`, `tests/domain/test_jobs_backup.py`

**Interfaces:**
- Produces: `PruneResult` (dataclass: `removed: list[Path]`, `stayed: list[Path]`); `prune(now, days) -> PruneResult`. Every caller and test that used the list is updated.

- [ ] **Step 1: Failing tests** (AC-145): with `shutil.rmtree` patched to raise `OSError` for one directory, `prune` returns it in `stayed` and the rest in `removed`; `call_command("backup")` prints "Backup made" and then raises `CommandError` (non-zero exit) when something stayed; the stderr or error text holds the count and no path; the `jobs` pass logs the count that stayed (use `caplog`), with no path.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Keep the log by exception type in `_remove`.
- [ ] **Step 4: Run, expect PASS** (also the existing prune tests, adapted to the return type); `make lint`.
- [ ] **Step 5: Commit** `fix(backup): a prune that leaves backups behind is not a success`.

---

### Task 6: Healthcheck of `jobs` and "Last pass" on the history page

**Files:**
- Modify: `deploy/compose.yaml` (jobs healthcheck and its comment), `app/api/admin_retention.py` (`history`), `app/api/jinja2/admin/retention.html` (the history template; find it from `history`), `docs/_architecture/modules/api-ui.md` later in Task 12
- Test: `tests/api/test_admin_retention.py`, `tests/test_deploy.py` or the existing compose test (find with `grep -rn compose tests | head`)

**Interfaces:**
- Consumes: `heartbeat.read_pass`, `heartbeat.jobs_healthy`.
- Produces: the history context has `last_pass` (a `PassRecord` or `None`); the template shows "Last pass: <finish in the configured time zone, `clock` helper>, <ok|failed>" or "No pass has finished yet"; with no record file at all the line is absent.

- [ ] **Step 1: Failing tests** (AC-144): history page after a recorded ok pass shows the finish time and the word for ok in cs and en; after a failed pass shows the failed text; with no record shows nothing; a compose test that the `jobs` service has a healthcheck whose `test` runs `python -m app.domain.heartbeat check` and is not `["CMD", "true"]`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Healthcheck `interval: 60s`, `timeout: 10s`, `start_period: 60s`, `retries: 3`; replace the comment about "a running container is healthy". Texts through `gettext` in the admin catalog.
- [ ] **Step 4: Run, expect PASS**; `make lint`; `docker compose -f deploy/compose.yaml config -q` (with the required environment variables of the existing compose tests) shows the file is valid.
- [ ] **Step 5: Commit** `feat(jobs): a real healthcheck and the last pass on the deletion history`.

---

### Task 7: Bad photo address logs nothing (TD-021)

**Files:**
- Modify: `app/urls.py:31`, `app/api/public.py` (`result_photo`)
- Test: `tests/api/test_retention_public.py` or the file that tests `result_photo` (`grep -rn result_photo tests | head -3`)

- [ ] **Step 1: Failing test** (AC-147): GET `/v/<token>/photo/not-a-uuid` answers 204 with the same private headers as an unknown id, and with `caplog` at WARNING for `django.request` no record contains the token.
- [ ] **Step 2: Run, expect FAIL** (today: 404 and a logged path).
- [ ] **Step 3: Implement.** Route `<str:answer_id>`; in the view `UUID(answer_id)` in a `try`, 204 via `_private(HttpResponse(status=204))` on `ValueError`; keep the existing flow for a valid UUID. Check the reverse call at `public.py:299` still resolves.
- [ ] **Step 4: Run, expect PASS** (the whole `tests/api` photo tests); `make lint`.
- [ ] **Step 5: Commit** `fix(public): a malformed result photo address no longer logs the token`.

---

### Task 8: No orphan photo files (TD-015)

**Files:**
- Modify: `app/api/play.py` (`with_files`, its two callers around `play.py:706` and the preview/other callers found by `grep -n with_files app`), `app/providers/media_local/provider.py` (`_saved`)
- Test: `tests/api/test_play_photos.py` or the existing file that tests `with_files` (`grep -rn with_files tests | head -3`), `tests/providers/test_media_local*.py`

**Interfaces:**
- `with_files(request, attempt, answers, read, lenient=False, stored: list[str] | None = None) -> list[str]`: when the caller passes `stored`, the function appends to that list, so the caller can remove whatever was written when anything raises. Without it, behaviour is as now.

- [ ] **Step 1: Failing tests** (AC-147): a submission with three photos where the second `store_participant_image` raises `OSError` leaves the first file neither on disk nor as a `MediaAsset` row (count files in `KVZ_MEDIA_PATH` and rows before and after); the same when `attempts.submit` raises an unexpected `Exception` after the photos were stored (already handled by the caller; keep it green); `_saved` with `asset.save` raising removes the written file.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** The caller in `submit` owns `stored` and calls `delete_images(stored)` for any exception raised by `with_files` itself. In `_saved`, remove the file with `missing_ok=True` when `asset.save()` raises and re-raise. Removal errors are swallowed with the exception type logged.
- [ ] **Step 4: Run, expect PASS**; `make lint`.
- [ ] **Step 5: Commit** `fix(play): photos written for a failed submission are removed`.

---

### Task 9: `email_key` and the cache (TD-076)

**Files:**
- Modify: `app/domain/models.py` (`Participant`), new migration `app/domain/migrations/00NN_participant_email_key.py` (next free number), `app/domain/participants.py` (the place at `participants.py:243-245` and any creation that sets `email`; find all with `grep -rn "email" app/domain/participants.py app/domain/attempts.py`), `app/domain/retention.py` (`search_email`, `erase`), `app/domain/results.py` (a public `clear_board_cache(run_id)` next to the key at `results.py:270`)
- Test: `tests/domain/test_retention_erasure.py`, `tests/domain/test_participants*.py`, a migration test next to the existing ones (`ls tests | grep -i migr`)

**Interfaces:**
- Produces: `Participant.email_key = CharField(max_length=254, null=True, blank=True, db_index=True)`; `participants.email_key_of(email: str | None) -> str | None` (strip and casefold, `None` for empty or none); `results.clear_board_cache(run_id) -> None` (deletes the `kvz-board:<run>:<locale>` keys for every locale the run's revision supports; read the locale list from the existing board code).

- [ ] **Step 1: Failing tests** (AC-146): saving an identity with an address sets `email_key` to its casefolded form; `search_email("  A@B.Example ")` finds the participant stored as `a@b.example` and as `A@B.Example`; `search_email` for many participants runs a fixed number of queries (`django_assert_num_queries` or `CaptureQueriesContext`, not growing with the count); an address stored without a key (simulate by `update(email_key=None)`) is not found by the new query, and the migration test shows the migration fills it for an existing row; after `erase`, a board request for the run no longer shows the erased nickname even within 5 s (prime the cache, erase, read the board); erasing clears `email_key` together with the row (the participant row is deleted, so the test asserts it is gone); the purge of a run leaves no `email_key` (rows are deleted).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** The migration adds the column and the index and fills existing rows in batches of 500 by `RunPython` with the same strip/casefold rule written inline (a migration must not import the live function); the reverse drops the column. Set `email_key` through `email_key_of` at every place that writes `Participant.email`. `search_email` filters on `email_key`. `erase` calls `results.clear_board_cache` for each affected run after its commit. Keep `fingerprint` and `erased_records` unchanged.
- [ ] **Step 4: Run, expect PASS** including `make wiring`, `tests/test_layers.py` and the migration check (`uv run python manage.py makemigrations --check`); `make lint`.
- [ ] **Step 5: Commit** `feat(retention): erasure search by an indexed address key, board cache cleared on erase`.

---

### Task 10: The record of a purge (TD-072)

**Files:**
- Modify: `app/domain/retention.py`, `app/domain/management/commands/jobs.py`
- Test: `tests/domain/test_retention_purge.py`, `tests/domain/test_retention_pass.py`, `tests/domain/test_retention_erasure.py`

Read TD-072 in `docs/_architecture/TECH_DEBT.md` first; each of its five effects is one failing test.

- [ ] **Step 1: Failing tests** (one each): a manual purge that stopped after the summary and was resumed by `run_pass` is recorded with trigger `manual` (keep the trigger in `retention_summary_json` when the summary is written, read it in `_finish`); a stopped purge followed by an erasure counts each row once (count from the summary); the "no results exporter" warning appears once per `run_pass` with several runs (`caplog`); a late export removal that failed once is retried (a pending marker, or a retry step in the next pass; the builder picks the mechanism and documents it in the test name); `run_pass` stops between runs when a `stop` callable returns true, and `jobs` passes its stop event.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** with the smallest change for each; `run_pass(now=None, stop=None)` keeps its call sites working.
- [ ] **Step 4: Run, expect PASS** (all `tests/domain/test_retention*.py`); `make lint`.
- [ ] **Step 5: Commit** `fix(retention): accurate record of a purge and a stop flag between runs`.

---

### Task 11: Tests and contracts of retention (TD-074, TD-075)

**Files:**
- Modify: `tests/contracts/retention.py`, the contract suites for media and exporter in `tests/contracts/`, `app/providers/retention/provider.py` (validate `trigger` in `record`), `app/contracts/__init__.py` only if the allowed triggers need a named constant
- Test: `tests/domain/test_retention*.py`, `tests/api/test_admin_retention.py`

Read TD-074 and TD-075 first; the bullet points there are the list.

- [ ] **Step 1: Failing tests:** `record` with an unknown trigger raises `ValueError` (retention suite); the new media methods (`private_assets_older_than`, `delete_image` of a missing id) and the exporter methods (`delete_for_runs`) are exercised by their shared contract suites; one test for each TD-075 case: the `by_revision` freeze with several revisions, a failure inside `_finish`, `delete_now` refused on a scheduled run, draw actions refused on a deleted run, the `ProtectedError` path in `_finish`.
- [ ] **Step 2: Run, expect FAIL** where behaviour is new (the `trigger` check) and PASS where it only adds coverage; say which in the commit body.
- [ ] **Step 3: Implement** the `trigger` validation (allowed: `automatic`, `manual`, `erasure`, the `AUTOMATIC`, `MANUAL`, `ERASURE` constants) and change the list comparison in the retention suite to a set.
- [ ] **Step 4: Run, expect PASS**; `make lint`.
- [ ] **Step 5: Commit** `test(retention): close the gaps of TD-074 and TD-075`.

---

### Task 12: TD-086 measurement, documents and archive

**Files:**
- Modify: `tools/load_participants.py`, `deploy/load.sh`, `docs/deployment.md`, `docs/privacy.md`, `docs/_architecture/` (`adr/0061-heartbeat-and-restore-marker.md`, `adr/README.md`, `adr/0059-backup-and-restore.md` and `adr/0056-retention-job-summary-held-runs.md` "Refined by", `acceptance-criteria.md` AC-143..AC-147, `data-model.md`, `security.md`, `modules/api-ui.md`, `modules/domain.md`, `roadmap.md` note, `TECH_DEBT.md` and the archive via `make tech-debt-resolve`), `app/domain/CLAUDE.md`, `app/api/CLAUDE.md`, root `CLAUDE.md`, `.claude/skills/kvizotron-check-integration/flows.md`, catalogs via `make messages`

- [ ] **Step 1: Measure TD-086.** With `make load` stack (or `docker compose -p kvizotron-load`), send requests with `curl --interface 127.0.0.2` (or `--local-addr`) and with the default source to the published port of the load stack, and read which client address the application records or limits (the `probe` quiz and `login`/start limits show it). Write the finding (told apart or not) in the report file. If told apart: use both sources in the probe in `tools/load_participants.py`, drop the "not told apart" result line and its sentence in `docs/deployment.md`, and close the first half of TD-086 (the text of the TD is rewritten to the photo-with-reveal half only). If not: rewrite the TD text with the measurement and leave it open.
- [ ] **Step 2: Documents.** ADR-0061 (heartbeat files and the pass record, the marker, the stale limit and why files and not rows, why `email_key` and not a fingerprint) with "Refined by" lines in ADR-0059 and ADR-0056; AC-143..AC-147 in `acceptance-criteria.md`; `docs/deployment.md` Restore section (the heartbeat refusal and its wait, the marker, the changed recovery: the refusal names the directory, the last step removes the marker, the "which pre-restore is the good one" text is replaced); `docs/privacy.md` and `data-model.md` for `email_key`; `security.md` log note; `api-ui.md` for the history page line and the `result_photo` route; `domain.md`, the `CLAUDE.md` files and `flows.md`; `roadmap.md` note; root `CLAUDE.md` (the sentences on restore, `jobs` and the erasure).
- [ ] **Step 3: Close the TDs** with `make tech-debt-resolve id=TD-NNN` for TD-068, 085, 082, 089, 021, 076, 015, 072, 074, 075 (and TD-086 only if fully closed); `make tech-debt-check`.
- [ ] **Step 4: `make messages`**; `git status` and commit only the catalogs that changed (revert unrelated `.mo` rewrites with `git checkout`).
- [ ] **Step 5: Run `make quality`**, expect green; commit `docs(d5): follow-up 2 decisions, criteria and archive`.

---

## Final steps (controller, not a task)

`make quality`, `make smoke` (`SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543`), `make load` (restore drill with the heartbeat wait), `kvizotron-check-applied`, a browser walkthrough of the Deletion history page with quiz prefix `d7` (rebuild the `kvizotron-browser` stack only as the skill says), then a whole-branch review on the most capable model with attention to the restore order and what `prune` may delete.

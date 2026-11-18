# D3 Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Personal data of a run are deleted automatically after its period, with an anonymous summary kept, manual deletion and erasure across runs, and a visible trail.

**Architecture:** `app/domain/retention.py` decides what is due and deletes, because only the domain may touch its models (`app/providers/CLAUDE.md` forbids providers importing `app/domain`). Provider `retention.local` owns the `retention_job` table behind a new `RetentionProvider` contract, the same split as D2's export. A deleted run is rewritten to hold what profile `none` holds, so export, statistics and the scoreboard reuse their existing `none` paths.

**Tech Stack:** Django, SQLite (WAL, `transaction_mode: IMMEDIATE`), Jinja2, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-09-d3-retention-design.md`

## Global Constraints

- No personal value in `audit_event`, `retention_job`, a log or an event payload.
- `Attempt.participant`, `Attempt.run`, `Attempt.replaced_by` are `PROTECT`: untie `replaced_by` first, delete attempts before participants.
- UI texts in cs, en and uk through `make messages`; "běh", never "kolo".
- An e-mail typed by an admin only ever travels in a POST body, never a URL.
- No new setting and no new dependency. Constants: pass every 3600 s, warning 14 days, batch 200 attempts, sweep age 1 hour.
- Periods in days: `30d`=30, `90d`=90, `180d`=180, `1y`=365, `3y`=1095, `permanent`=none.
- Run single test files with `uv run pytest <path> -v`; `make quality` before the last commit of each task that changes code. Work on branch `feat/d3-retention`.
- Each test named for an acceptance criterion has that `AC-xx` in its docstring (`tests/test_docs.py` looks for it).

## Review Focus

- An erased person's next request on a token already in hand (play, submit, private link): the normal "not available" answer, not a 500.
- Draw and rewards pages of a run whose participants are gone: pseudonym shown, not a 500.
- `  Jan@Example.CZ ` typed with other case and spaces: finds the row, and yields the same fingerprint as `jan@example.cz`.
- A pass that dies halfway: the next pass finishes the run, the summary is not recomputed from half the rows, one history row exists.
- A photo file already missing from the volume: the run is still processed.

---

### Task 1: Retention provider and contract additions

**Files:**
- Modify: `app/contracts/__init__.py`, `pyproject.toml` (entry point), `app/providers/csv_io/results.py`, `app/providers/media_local/provider.py`
- Create: `app/providers/retention/{__init__,apps,manifest,models,provider}.py`, `app/providers/retention/migrations/{__init__,0001_initial}.py`, `tests/contracts/retention.py`, `tests/contracts/test_retention.py`
- Test: `tests/providers/test_export_retention.py`

**Interfaces:**
- Produces in `app.contracts`:
  - `RetentionRecord` (frozen dataclass): `id: str, run_id: str, trigger: str, admin_id: str | None, policy: str, cutoff_at: datetime | None, executed_at: datetime, counts: Mapping[str, int], has_fingerprint: bool`
  - `RetentionProvider` Protocol, id `"local"`: `record(run_id: str, *, trigger: str, admin_id: str | None, policy: str, cutoff_at: datetime | None, counts: Mapping[str, int], fingerprint: str | None = None) -> str`; `history(limit: int = 200) -> Sequence[RetentionRecord]` newest first; `for_run(run_id: str) -> Sequence[RetentionRecord]`; `erased(fingerprint: str) -> Sequence[RetentionRecord]`
  - `"retention": RetentionProvider` in the capability map.
  - `trigger` values: `"automatic"`, `"manual"`, `"erasure"`.
  - `MediaStorageProvider.private_assets_older_than(cutoff: datetime) -> Sequence[str]`
  - `ResultsExporterProvider.delete_for_runs(quiz_id: str, run_ids: Sequence[str]) -> None`

- [ ] **Step 1:** Write `tests/contracts/retention.py`, a shared suite over any `RetentionProvider`, used by `test_retention.py`: `record` then `history` returns it with exact counts; `erased(fp)` finds only rows with that fingerprint; `for_run` filters; `RetentionRecord` exposes `has_fingerprint`, never the value. In `test_retention.py` add `manifest.settings == []`, `provides == ["retention"]`, `id == "retention.local"`.
- [ ] **Step 2:** Write `tests/providers/test_export_retention.py`: a `done` job naming a run loses row and directory; a job with `all_runs` of that quiz likewise; a job of another quiz stays; a `queued` and a `running` job become `failed` with error `"run_data_deleted"` and a later `write` leaves no files. Media: `private_assets_older_than` returns a private asset older than the cutoff, not a newer one, not a public one.
- [ ] **Step 3:** Run both; expected FAIL on import.
- [ ] **Step 4:** Implement. Table `retention_job` has the columns of `docs/_architecture/data-model.md` plus `trigger`, `admin_id` (nullable), `fingerprint` (nullable, indexed); `run_id` is a plain string, no foreign key. Manifest id `retention.local`, app `app.providers.retention.apps.RetentionConfig`, `"settings": []`. `delete_for_runs` matches `choices_json["quiz"] == quiz_id` with `all_runs`, or any id in `choices_json["runs"]`. Run `uv sync` so the entry point is found.
- [ ] **Step 5:** Run both, expected PASS; `make wiring`, expected PASS.
- [ ] **Step 6:** Commit `feat(retention): provider, contract and export and media hooks`.

### Task 2: Run fields, due date and held runs

**Files:**
- Modify: `app/domain/models.py` (`QuizRun`), `app/domain/data_policy.py`
- Create: `app/domain/migrations/0019_retention.py`, `tests/domain/test_retention_due.py`, `tests/domain/test_migration_0019.py`

**Interfaces:**
- Produces: `QuizRun.data_deleted_at: datetime | None`, `QuizRun.retention_held_at: datetime | None`, `QuizRun.retention_summary_json: dict` (default `{}`).
- Produces in `data_policy`: `PERIOD_DAYS: Mapping[str, int]`; `deletion_at(run: QuizRun) -> datetime | None`, None for a test run, a run with no `closed_at`, a permanent period or a deleted run; `is_due(run, now) -> bool`, `deletion_at <= now` and not held; `days_left(run, now) -> int | None`; `WARNING_DAYS = 14`; `deletion_soon(run, now) -> bool`.

- [ ] **Step 1:** Write tests. AC-110 in docstring: due exactly at `closed_at + 90 days`; not due one second before; permanent, never closed, held, deleted and test runs not due; `1y` is 365 days. `deletion_soon` true at 14 days left, false at 15. Migration test in the style of `tests/domain/test_migration_0015.py`, AC-114 in docstring: a closed run past its period gets `retention_held_at`; a closed run within it, a permanent one and an open one do not.
- [ ] **Step 2:** Run, expected FAIL.
- [ ] **Step 3:** Add the fields and functions. The migration's data step uses its own copy of the day table, treats a missing period as `90d`, and only touches `kind="normal"` rows.
- [ ] **Step 4:** Run, expected PASS.
- [ ] **Step 5:** Commit `feat(retention): run deletion date and held runs`.

### Task 3: Deleting a run and keeping its summary

**Files:**
- Create: `app/domain/retention.py`, `tests/domain/test_retention_purge.py`
- Modify: `app/domain/run_stats.py`
- Test also: `tests/domain/test_retention_stats.py`

**Interfaces:**
- Consumes: Task 1 provider through `registry.get("retention", "local")`, Task 2 fields.
- Produces in `retention`: `purge_run(run: QuizRun, *, trigger: str, admin_id: str | None) -> bool`, False when already deleted; `Refused(Exception)` with `.code`; `delete_now(run, *, admin_id: str) -> None`, code `"not_ended"` unless CLOSED or ARCHIVED.
- Produces in `run_stats`: `freeze(stats: RunStats) -> dict`, JSON-safe with `Decimal` as strings and question stats holding only `question_id, answered, average, full_share`; `of_run` and `comparison` return the frozen values when `run.retention_summary_json` is set, finding each question's text again through `selection.all_questions` of the run's revisions.

Stages of `purge_run`, each its own transaction:

1. If no summary yet: store `freeze(of_run(run))` plus `"counts"` (rows of each kind about to go) in `retention_summary_json`, clear `replaced_by` on the run's attempts.
2. Repeat: take 200 attempt ids, collect their `asset_id`s, delete them, delete those assets after commit with `delete_image`, catching and logging by run id.
3. Last: delete `HiddenAnswerValue`, `RewardEntitlement`, `Participant` of the run; set `retention_json` profile to `none`, `stateless_submitted` to the summary's submitted count, `status` ARCHIVED, `retention_held_at` None; update `data_deleted_at` conditioned on it being null. Only when that update changed a row: `RetentionProvider.record`, `audit.record` with action `run.data_deleted` and the counts, `events.emit("retention.executed", {"run_id": ...})`, and `delete_for_runs`.

- [ ] **Step 1:** Write `test_retention_purge.py`. AC-111: after purge no participant, attempt, answer, entitlement or photo asset of the run remains; the run, revisions, reward rules and `draw_entry` with its pseudonym and `participant_id is None` remain; another run's rows are untouched. A `replaced_by` chain deletes without `ProtectedError`. A photo file already missing does not stop it. Purging twice leaves one record. A simulated failure after stage 1, then a second purge, gives one record with the original counts. AC-115: `delete_now` matches expiry and is refused on an open run with `"not_ended"`. A run with no attempts and a run with profile `none` purge cleanly.
- [ ] **Step 2:** Write `test_retention_stats.py`, AC-112: `of_run` and `comparison` return equal numbers before and after purge; `questions` is present for profile `answers`, None with reason `"profile"` for `score`.
- [ ] **Step 3:** Run, expected FAIL.
- [ ] **Step 4:** Implement.
- [ ] **Step 5:** Run, expected PASS.
- [ ] **Step 6:** Commit `feat(retention): delete a run's data and keep a summary`.

### Task 4: The pass, its commands and the jobs service

**Files:**
- Modify: `app/domain/retention.py`, `deploy/compose.yaml`, `deploy/smoke.sh`
- Create: `app/domain/management/__init__.py`, `app/domain/management/commands/{__init__,retention,jobs}.py`, `tests/domain/test_retention_pass.py`

**Interfaces:**
- Produces: `retention.run_pass(now: datetime | None = None) -> int` number of runs purged; `retention.sweep(now: datetime) -> int`; `jobs.run_loop(stop: threading.Event, wait: Callable[[float], bool], one_pass: Callable[[], object]) -> None`.

- [ ] **Step 1:** Write tests. AC-119: `call_command("retention")` purges a due run with trigger `"automatic"` and `admin_id None`; a failing purge on one run leaves the other purged and logs the id only; `run_pass` twice gives one record; a run whose deadline passed but was not settled gets `closed_at` first. Sweep: a private asset older than an hour with no `AttemptAnswer.asset_id` goes; a newer one, a referenced one and a public one stay. `run_loop` makes one pass, then stops when `stop` is set.
- [ ] **Step 2:** Run, expected FAIL.
- [ ] **Step 3:** Implement. `run_pass` calls `run_schedule.settle(now)`, then purges each due run, then sweeps. `jobs` sets `stop` on SIGTERM, makes a pass at start and then waits 3600 s, and calls `close_old_connections()` around each pass; an exception in a pass is logged and the loop goes on. Service in compose: `jobs`, `<<: *app`, `command: ["python", "manage.py", "jobs"]`, `depends_on: migrate: service_completed_successfully`, `restart: unless-stopped`, `healthcheck: disable: true` as the image's check calls port 8000.
- [ ] **Step 4:** Add to `deploy/smoke.sh` a check that `jobs` is running and that `manage.py retention` exits 0 inside it.
- [ ] **Step 5:** Run tests, expected PASS; `make smoke` (with `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543` when `kvizotron-browser` runs), expected PASS.
- [ ] **Step 6:** Commit `feat(retention): hourly pass and jobs service`.

### Task 5: What a deleted run and a changed period do

**Files:**
- Modify: `app/domain/run_schedule.py` (`set_period`), `app/domain/results.py` (`_hidden`), `app/domain/walkthrough.py` (`available`), `app/api/scoreboard.py`
- Create: `tests/domain/test_retention_period.py`, `tests/api/test_retention_public.py`

**Interfaces:**
- Produces: `run_schedule.set_period(run, period, *, admin_id, confirmed: bool = False) -> None`; `ScheduleRefused("data_deleted")`; `run_schedule.PeriodNeedsConfirmation(Exception)`, raised when the change would make a run not already due due at once and `confirmed` is False; board reason `"data_deleted"` in `Board.hidden`.

- [ ] **Step 1:** Write tests. AC-114: shortening into the past without confirmation raises and changes nothing; with it the next pass deletes; extending a held run past now clears the hold; lengthening needs no confirmation. AC-113: a deleted run refuses a period change; `restore` gives CLOSED with data still gone, and the pass skips it; public scoreboard (also with `ARCHIVED_RESULTS` on, and after restore), walkthrough and private link show the unavailable message with no 500; an in-progress attempt's token after its row is gone gets the existing error page on play and submit. An export of a deleted run holds only the submitted count (AC-111). The draw and rewards admin pages of a deleted run answer 200 and show the pseudonym.
- [ ] **Step 2:** Run, expected FAIL.
- [ ] **Step 3:** Implement. `_hidden` tests `run.data_deleted_at` first. Map `"data_deleted"` in `scoreboard.py` to the same text as `"archived"`. Any 500 the tests expose is fixed at the place that dereferenced the missing row.
- [ ] **Step 4:** Run, expected PASS.
- [ ] **Step 5:** Commit `feat(retention): deleted runs on public pages and shortened periods`.

### Task 6: Erasure across runs

**Files:**
- Modify: `app/domain/retention.py`
- Create: `tests/domain/test_retention_erasure.py`

**Interfaces:**
- Produces: `Found` (frozen dataclass: `participant_id: str, run_id: str, quiz_id: str, run_no: int | None, display_name: str, email: str | None`); `retention.search_email(raw: str) -> list[Found]`; `retention.search_name(raw: str) -> list[Found]`; `retention.fingerprint(raw_email: str) -> str`, `salted_hmac("kvz-erasure", normalised, algorithm="sha256").hexdigest()` where normalised is `raw.strip().casefold()`; `retention.erase(participant_ids: Sequence[str], *, admin_id: str, email: str | None = None) -> None`, one record per affected run with trigger `"erasure"`; `retention.erased_records(raw_email: str) -> Sequence[RetentionRecord]`.

- [ ] **Step 1:** Write tests. AC-116: e-mail search finds a person across two runs including a test run, with different case and spaces; name search compares `name_key`; `erase` of chosen ids removes them with attempts, answers, photos and entitlements, leaves other participants, keeps draw pseudonyms, does not archive the run, works on an open run; export files naming the run go. AC-117: after an erasure by e-mail, `erased_records` with other case and spaces finds it, the address appears in no column of `retention_job` or `audit_event`, and `AuditEvent.details_json` holds counts only; erasure by name stores no fingerprint.
- [ ] **Step 2:** Run, expected FAIL.
- [ ] **Step 3:** Implement, sharing the attempt deletion helper with `purge_run`. Search through `Participant.objects`, which includes test runs.
- [ ] **Step 4:** Run, expected PASS.
- [ ] **Step 5:** Commit `feat(retention): erasure across runs`.

### Task 7: Administration pages

**Files:**
- Create: `app/api/admin_retention.py`, `app/api/jinja2/admin/retention.html`, `app/api/jinja2/admin/erasure.html`, `tests/api/test_admin_retention.py`
- Modify: `app/api/admin_urls.py`, `app/api/admin_runs.py` (`run_period`, `_run_context`, the runs list rows), `app/api/jinja2/admin/{base,run,runs}.html`, the admin stylesheet in `app/api/assets/`, `app/api/locale/*`

**Interfaces:**
- Consumes: everything above.
- Produces routes: `retention_history` GET `retention`; `retention_held` POST `retention/held`; `retention_erasure` GET and POST `retention/erasure`; `retention_verify` POST `retention/verify`; `admin_run_delete_data` POST `runs/<uuid:run_id>/delete-data`.

- [ ] **Step 1:** Write tests. AC-117: history lists an automatic, a manual and an erasure row with who, when, run and counts, and the run page links to its own row; verify answers yes with date and admin for an erased address and no for another. AC-114: held runs are listed above the history; POST with `confirm=1` releases them to the next pass, and without it asks; the period form shows `admin/confirm.html` when a confirmation is needed. AC-115: delete-data without `confirm=1` shows the confirmation naming what goes, and with it deletes. AC-116: an erasure shows found rows in a response with `Cache-Control: no-store`, deletes only ticked rows after confirmation. AC-118: the date shows on the run page and in the runs list; at 9 days left the element has class `deletion-soon` and text with `9`; at 30 days not; a deleted run shows the label instead.
- [ ] **Step 2:** Run, expected FAIL.
- [ ] **Step 3:** Implement with `admin_required`, `require_POST` where a route only takes POST, the existing `admin/confirm.html`. A nav entry "Deletion history" in `base.html`. `can_set_period` false on a deleted run. Rule `.deletion-soon` passes WCAG AA in all five palettes, using an existing token if one does.
- [ ] **Step 4:** Run `make messages`, fill cs and uk, run tests, expected PASS; `make wiring`, expected PASS.
- [ ] **Step 5:** Commit `feat(retention): deletion history, erasure and run page`.

### Task 8: Documents and closing

**Files:**
- Create: `docs/_architecture/adr/0056-retention-job-summary-held-runs.md`
- Modify: every row of the table in section 4 of `.claude/skills/kvizotron-milestone/SKILL.md`, plus `docs/privacy.md`, `docs/deployment.md`, `docs/_architecture/providers/retention.md`, `docs/_architecture/architecture.md` (scheduled jobs row), `docs/_architecture/modules/contracts.md`, `app/api/jinja2/public/privacy.html`

- [ ] **Step 1:** ADR-0056: hourly `jobs` service, summary then profile `none` rewrite, held runs, HMAC of the e-mail, the domain and provider split. `privacy.md`: replace each "until D3" and "comes in a later version" sentence, add the fingerprint. `deployment.md`: `jobs` service, the effect of rotating `KVZ_SECRET_KEY`. Public privacy page: say deletion happens, and `make messages`.
- [ ] **Step 2:** Add AC-110 to AC-119 with Stage D to `acceptance-criteria.md` using the texts in the spec, mark D3 done with `Done 2026-11-09` or the real day in `roadmap.md`, update `CLAUDE.md` Status and "Next is D4".
- [ ] **Step 3:** Run `make tech-debt-resolve id=TD-067`.
- [ ] **Step 4:** Run `make quality`, expected all PASS including `tests/test_docs.py`.
- [ ] **Step 5:** Commit `docs(retention): D3 documents`.

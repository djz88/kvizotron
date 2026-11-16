# D2 Results Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admins export results, participants, statistics, answers, rewards and draws of one run, a whole quiz or picked runs as `;`-CSV files or one ZIP, prepared in a background thread and downloadable for 24 hours.

**Architecture:** The domain (`app/domain/results_export.py`) decides which rows a run gives under its data profile and formats them into `ExportTable`s. The `csv.io` provider gets a new port `results_exporter` that owns `export_job` rows, slots and files on the media volume, and writes CSV/ZIP. The API (`app/api/admin_results_export.py`, `app/api/export_runner.py`) holds the page, the thread and downloads, and talks to the provider only through the registry. FR-44 gets a separate port `table_sink` with only a test fake.

**Tech Stack:** Django, Jinja2, HTMX, stdlib `csv`, `zipfile`, `threading`, SQLite WAL, pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-d2-results-export-design.md`

## Global Constraints

- CSV: delimiter `;`, UTF-8 with BOM, CRLF, header row in the admin's language at job creation.
- Every cell through formula protection (`'` before `=`, `+`, `-`, `@`, tab, CR), except a value in a column listed as numeric that matches `^-?\d+([.,]\d+)?$`.
- Numbers: decimal comma for `cs` and `uk`, point for `en`. Times: ISO 8601 with offset in the configured time zone (`app/domain/clock.py`).
- Each row of every file starts with columns `run` (run number) and `revision` (revision number); `questions` rows under profile `none` carry `revision` empty.
- Never in a file: answer keys, access-code hash, attempt or test-link tokens. Never in audit: names, e-mails, answers.
- Left out of every file: unsubmitted attempts, test runs (`QuizRun.Kind.TEST`), test-link attempts.
- Job link valid 24 hours (`expires_at = created_at + 24 h`); at most 1 running job per admin, 2 in the app.
- Layers per `tests/test_layers.py`: `api` must not import `providers`; `domain` must not import `api`, `plugins`, `providers`.
- No new dependency. Strings through `gettext`; `make messages`, cs and uk `msgstr` filled.
- Each AC is named in a test docstring (`"""AC-1xx."""`).

## Review Focus

- Admin edits URL `runs=` with a run of another quiz or a test run → 404, never exported. (Task 4, `test_foreign_run_refused`.)
- Two admins: B opens A's job status, restart or download URL → 404. (Task 2 `test_job_belongs_to_admin`, Task 4 `test_download_other_admin_404`.)
- Text answer `=HYPERLINK(...)` and nickname `-1` (text column) → written with leading `'`; score `-1` in numeric column stays `-1`. (Task 1 `test_numeric_exemption_only_in_numeric_columns`.)
- Process restart while a job is `running` → shown `interrupted` with a restart button, slot freed. (Task 2 `test_stale_jobs_become_interrupted`.)
- Photo asset missing on disk (deleted) → ZIP still built, answers row says the photo name, no crash. (Task 4 `test_missing_photo_skipped`.)

---

### Task 1: Contracts and table writer

**Files:**
- Modify: `app/contracts/__init__.py` (next to `ExporterProvider`, and `PORTS`)
- Modify: `app/providers/csv_io/writer.py`
- Create: `tests/contracts/table_sink.py` (shared suite), `tests/support/sheets_fake.py`, `tests/contracts/test_table_sink.py`
- Test: `tests/providers/test_csv_writer.py`

**Interfaces:**
- Produces in `app.contracts`:
  - `@dataclass(frozen=True) class ExportTable: name: str; columns: Sequence[str]; headers: Sequence[str]; rows: Sequence[Mapping[str, str]]; numeric: frozenset[str] = frozenset()` (`columns` are keys, `headers` translated labels, same length).
  - `@dataclass(frozen=True) class ExportJobView: id: str; status: str; choices: Mapping[str, Any]; files: Sequence[str]; error: str | None; created_at: datetime; expires_at: datetime`; status values `"queued" | "running" | "done" | "failed" | "interrupted"`.
  - `class ExportJobGone(Exception)`.
  - `@runtime_checkable class TableSinkProvider(Protocol): id: str; def send(self, title: str, tables: Sequence[ExportTable]) -> str: ...` (returns where it went). Port `"table_sink"`.
  - `@runtime_checkable class ResultsExporterProvider(Protocol)` with `id: str` and:
    - `create(admin_id: str, choices: Mapping[str, Any]) -> str`
    - `job(job_id: str, admin_id: str) -> ExportJobView` (raises `ExportJobGone` when missing, foreign or expired)
    - `jobs(admin_id: str) -> Sequence[ExportJobView]` (unexpired, newest first)
    - `claim_next() -> ExportJobView | None` (the job it set running, with its choices)
    - `write(job_id: str, tables: Sequence[ExportTable], photos: Mapping[str, str], bundle: bool) -> None` (`photos`: name in ZIP → filesystem path)
    - `fail(job_id: str, code: str) -> None`
    - `restart(job_id: str, admin_id: str) -> str`
    - `path(job_id: str, admin_id: str, name: str) -> str` (raises `ExportJobGone`)
    - Port `"results_exporter"`.
  - `writer.write_table(table: ExportTable, out: IO[str]) -> None` in `app/providers/csv_io/writer.py`.

- [ ] **Step 1: Failing tests** in `tests/providers/test_csv_writer.py`:
  - `test_table_is_semicolon_bom_crlf` — `"""AC-102."""`; table with headers `["Běh", "Skóre"]`, one row; output starts with `"﻿Běh;Skóre\r\n"`.
  - `test_numeric_exemption_only_in_numeric_columns` — `"""AC-102."""`; columns `name`, `score`, `numeric={"score"}`; row `{"name": "-1", "score": "-1,5"}` → `"'-1;-1,5"`; row `{"name": "=HYPERLINK(1)", "score": "=1"}` → both protected with `'`.
  - `tests/contracts/test_table_sink.py::test_fake_passes_suite` — `"""AC-109."""`; `TableSinkSuite` in `tests/contracts/table_sink.py` asserts `isinstance(fake, TableSinkProvider)`, `send("t", [table])` returns non-empty `str`, and the fake keeps the tables it got unchanged.
- [ ] **Step 2:** `uv run pytest tests/providers/test_csv_writer.py tests/contracts/test_table_sink.py -q` → FAIL (import errors).
- [ ] **Step 3:** Add the contract types and ports; `write_table` with `csv.writer(out, delimiter=";", lineterminator="\r\n")`, BOM first, header row from `headers`, cells via `protect` unless numeric-exempt. Existing `write_csv` (questions, comma) unchanged. `tests/support/sheets_fake.py`: `class SheetsFake` keeping `sent: list[tuple[str, list[ExportTable]]]`.
- [ ] **Step 4:** Same command → PASS; `uv run pytest tests/test_layers.py tests/contracts -q` → PASS.
- [ ] **Step 5:** Commit `feat(export): table contracts, Sheets port and semicolon writer`.

### Task 2: Export jobs in `csv.io`

**Files:**
- Modify: `app/providers/csv_io/models.py` (add `ExportJobRecord`, `db_table = "export_job"`), new migration in `app/providers/csv_io/migrations/`
- Create: `app/providers/csv_io/results.py` (`CsvResultsExporter`)
- Modify: `app/providers/csv_io/apps.py` (register `"results_exporter", "csv"`), `manifest.py` (`provides` += `"results_exporter"`), `limits.py` (`EXPORT_LIFETIME = timedelta(hours=24)`, `EXPORT_SLOTS_TOTAL = 2`, `EXPORT_SLOTS_PER_ADMIN = 1`)
- Test: `tests/providers/test_csv_results.py`, `tests/contracts/test_csv_io.py`

**Interfaces:**
- Consumes: Task 1 types.
- Produces: registry `"results_exporter", "csv"` implementing `ResultsExporterProvider`. Files under `<KVZ_MEDIA_PATH>/exports/<job id>/`, mode `0o640`. `ExportJobRecord` fields: `id` (uuid7), `admin_id`, `kind` (`"results"`), `status`, `choices_json`, `report_json` (`{"files": [...], "error": code}`), `boot` (str), `created_at`, `expires_at`. `BOOT = uuid.uuid4().hex` at module import of `results.py`.

- [ ] **Step 1: Failing tests** (`tests/providers/test_csv_results.py`):
  - `test_create_purges_expired` — expired job and its directory gone after `create`.
  - `test_slots` — `"""AC-105."""`; admin A two jobs, admin B one: `claim_next()` gives A's first, then B's, then `None` (A has one running, total 2).
  - `test_write_separate_and_bundle` — `"""AC-105."""`; `bundle=False` → one `.csv` per table named `<table.name>.csv`, `job().files` lists them, status `done`; `bundle=True` with `photos={"photos/1/x-2.webp": path}` → one `.zip` holding each CSV and the photo.
  - `test_stale_jobs_become_interrupted` — `"""AC-106."""`; a `running` row with `boot="old"` → `jobs(admin)` shows `interrupted`; `restart` creates a new `queued` job with the same `choices`.
  - `test_job_belongs_to_admin` — `"""AC-105."""`; `job(id, "other")` and `path(id, "other", name)` raise `ExportJobGone`; `path` with `"../x"` raises `ExportJobGone`.
  - In `tests/contracts/test_csv_io.py`: provider is `ResultsExporterProvider`, manifest `provides == {"importer", "exporter", "results_exporter"}`.
- [ ] **Step 2:** `uv run pytest tests/providers/test_csv_results.py tests/contracts/test_csv_io.py -q` → FAIL.
- [ ] **Step 3:** Implement `CsvResultsExporter`. `create` and `jobs` first purge expired rows+dirs and mark `queued`/`running` rows whose `boot != BOOT` as `interrupted`. `claim_next` inside `transaction.atomic()` (IMMEDIATE) flips the oldest eligible `queued` row to `running` with `boot=BOOT`. `write` streams each table to a file (or into `zipfile.ZipFile` opened on a file path, `ZIP_DEFLATED`, photos added by `archive.write(path, name)`, skipping a missing path), then sets `done`. ZIP name `results.zip`. `path` checks name is in `report_json["files"]`.
- [ ] **Step 4:** Same command → PASS; `uv run python manage.py makemigrations --check` → no changes.
- [ ] **Step 5:** Commit `feat(export): export jobs in csv.io`.

### Task 3: What a run exports (domain)

**Files:**
- Create: `app/domain/results_export.py`
- Test: `tests/domain/test_results_export.py`

**Interfaces:**
- Consumes: `ExportTable` (Task 1); existing `data_policy.of(run)`, `participants.attempt_rows` logic, `results.official_attempt`, `results.place_of`, `run_stats.of_run`, `RewardEntitlement`, `Draw`/`DrawEntry`, `clock`, question type `summarize` (answer text = `", ".join(item.label for item in plugin.summarize(definition, [answer_json], locale))`, photos give `photo: <zip path>`).
- Produces:
  - `FILES = ("attempts", "participants", "questions", "answers", "entitlements", "draws")`; `PERSONAL = frozenset(FILES) - {"questions"}`.
  - `runs_for(quiz: Quiz, run_ids: Sequence[str] | None) -> list[QuizRun]` — normal runs of that quiz only, ordered by `run_no`; unknown or foreign id raises `QuizRun.DoesNotExist`.
  - `offered(runs: Sequence[QuizRun]) -> dict[str, int]` — file → number of runs that provide it; files with 0 omitted.
  - `has_photos(runs: Sequence[QuizRun]) -> bool`.
  - `tables(runs: Sequence[QuizRun], files: Sequence[str], locale: str, *, photos: bool) -> list[ExportTable]`.
  - `photo_files(runs: Sequence[QuizRun]) -> dict[str, str]` — ZIP path `photos/<run_no>/<attempt id>-<question no>.<ext>` → `asset_id`.
  - `record_created(job_id: str, admin_id: str, choices: Mapping[str, Any]) -> None` (`export.created`, details: run ids, files, photos, `personal: bool`); `record_downloaded(job_id: str, admin_id: str, name: str) -> None` (`export.downloaded`).
  - `file_name(quiz: Quiz, runs: Sequence[QuizRun], all_runs: bool, at: datetime) -> str` → `<slug>-<run-N|all|runs>-<YYYYMMDD-HHMM>`.

Profile → files (spec table): `none` gives only `questions` (one row per run: `run`, `revision` empty, `submitted` = `stateless_submitted`); `score` all files, `answers` only answers needing grading (photo rows); `answers` and `detailed` everything; `duration` column only for `detailed`.

- [ ] **Step 1: Failing tests** using existing fixtures in `tests/fixtures` / `tests/conftest.py`:
  - `test_offered_follows_profile` — `"""AC-101."""`; runs with `none` and `answers` → `offered == {"questions": 2, "attempts": 1, ...}`; only `none` → `{"questions": 1}`.
  - `test_none_gives_counts_only` — `"""AC-101."""`; `tables([none_run], ["questions"], "cs", photos=False)` has one row with the count.
  - `test_answers_one_row_per_attempt_question` — `"""AC-103."""`; two submitted attempts × three questions (choice, number, matching) → six rows; choice cell equals the option text in cs; no cell contains `"correct"` key data or JSON braces.
  - `test_unsubmitted_and_test_runs_left_out` — `"""AC-103."""`.
  - `test_rows_carry_run_and_revision` — `"""AC-108."""`; quiz with runs 1 and 2 on revisions 1 and 2 → every attempts row has matching `run`, `revision`.
  - `test_numbers_and_times_by_locale` — score `7.5` → `"7,5"` in cs, `"7.5"` in en; `submitted_at` ends with the zone offset.
  - `test_headers_in_admin_language` — `"""AC-102."""`; headers of `attempts` differ between `cs` and `en` and keys stay the same.
  - `test_audit_has_no_personal_values` — `"""AC-107."""`; participant e-mail and name not in any `details_json`.
  - `test_foreign_run_refused` — `runs_for(quiz_a, [run_of_quiz_b])` and a test run raise.
- [ ] **Step 2:** `uv run pytest tests/domain/test_results_export.py -q` → FAIL.
- [ ] **Step 3:** Implement. Translate headers with `translation.override(locale)` + `gettext`. Question texts in `locale`, else quiz `default_locale`. Draw rows: one per `Draw` with winners/alternates as `nickname (participant id)` joined by `, `; no e-mail. Entitlement rows include e-mail.
- [ ] **Step 4:** Same command → PASS; `uv run pytest tests/test_layers.py -q` → PASS.
- [ ] **Step 5:** Commit `feat(export): rows of results, participants, statistics, answers, rewards and draws`.

### Task 4: Export page, thread and downloads

**Files:**
- Create: `app/api/admin_results_export.py`, `app/api/export_runner.py`, `app/api/jinja2/admin/results_export.html`, `app/api/jinja2/admin/_export_jobs.html`
- Modify: `app/api/admin_urls.py`; run page tab (`app/api/jinja2/admin/run.html`), quiz header (`_quiz_header.html`), runs comparison (`runs.html`, checkboxes + "Export selected" as GET form)
- Modify: locale files via `make messages`
- Test: `tests/api/test_results_export.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: URLs
  - `GET/POST /admin/exports/new?quiz=<id>&runs=<id,…>` name `results_export_new` (no `runs` = all runs of the quiz)
  - `GET /admin/exports/jobs` name `results_export_jobs` (HTMX fragment, polls every 2 s via `hx-trigger="every 2s"` only while some job is `queued`/`running`)
  - `POST /admin/exports/<job>/restart` name `results_export_restart`
  - `GET /admin/exports/<job>/<name>` name `results_export_download`
  - `export_runner.kick() -> None`; `export_runner.SPAWN: Callable[[Callable[[], None]], None]` (default starts `threading.Thread(daemon=True)`; tests set it to call directly).

POST form fields: `files` (multi), `photos` (`on`), `bundle` (`"zip"` | `"separate"`), `personal_ok` (`on`). Choices stored: `{"quiz", "runs", "all_runs", "files", "photos", "bundle", "locale", "name"}`. Runner `_run(job_id)`: read choices, `runs_for`, `tables`, photos via `media_storage().load(asset_id).path`, `provider.write`; any exception → `provider.fail(job_id, "error")` with `logger.exception` without row data; `finally: django.db.connection.close()` and `kick()`.

- [ ] **Step 1: Failing tests** (`tests/api/test_results_export.py`, `export_runner.SPAWN` patched to synchronous):
  - `test_page_lists_only_offered_files` — `"""AC-101."""`.
  - `test_personal_needs_confirmation` — `"""AC-107."""`; POST with `attempts` and no `personal_ok` → 400, no job; with it → 302, audit `export.created`.
  - `test_download_csv_end_to_end` — `"""AC-102."""`; download `attempts.csv` → starts with BOM, `;`, cs headers; `Content-Disposition: attachment`, `Cache-Control` contains `no-store`; audit `export.downloaded`.
  - `test_zip_with_and_without_photos` — `"""AC-104."""`; photo run: `photos=on` → ZIP holds `photos/1/<attempt>-<n>.webp` and answers row names it; without → no `photos/` entries, answers row still names the file.
  - `test_missing_photo_skipped` — asset file deleted → job `done`, ZIP without it.
  - `test_download_other_admin_404` — `"""AC-105."""`; also expired job → 404.
  - `test_restart_interrupted` — `"""AC-106."""`.
  - `test_foreign_run_refused` — `runs=` with another quiz's run → 404.
  - `test_entry_points_link_to_export` — run page, quiz header and runs page contain the `results_export_new` URL.
- [ ] **Step 2:** `uv run pytest tests/api/test_results_export.py -q` → FAIL.
- [ ] **Step 3:** Implement views (`admin_required`), templates in the existing admin look, entry links; `make messages`, fill cs and uk.
- [ ] **Step 4:** Same command → PASS; `make test` → PASS.
- [ ] **Step 5:** Commit `feat(export): export page, background job and downloads`.

### Task 5: Documents, ADR and verification

**Files:**
- Create: `docs/_architecture/adr/0055-results-export-background-job-and-csv-dialect.md` (MADR 4, accepted)
- Modify: `docs/_architecture/adr/README.md`, `acceptance-criteria.md` (AC-101…AC-109 exactly as in spec Verification), `roadmap.md` (D2 `Done 2026-11-XX`), `providers/csv-io.md` (results export, `export_job`, ports), `modules/contracts.md` (new ports), `modules/api-ui.md` (URLs), `data-model.md` (`export_job` columns), `docs/privacy.md` (exports and audit), `CLAUDE.md` (milestones, Stav, „Další je D3“), `app/api/CLAUDE.md`, `app/domain/CLAUDE.md`, `app/providers/CLAUDE.md` or `csv_io` notes, `.claude/skills/kvizotron-check-integration/flows.md` (flow Export).

- [ ] **Step 1:** Write the docs; `uv run pytest tests/test_docs.py -q` → PASS (every AC named by a test).
- [ ] **Step 2:** `make quality` → all green.
- [ ] **Step 3:** `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke` → passes.
- [ ] **Step 4:** Commit `docs(export): D2 ADR-0055, AC-101 to AC-109 and module docs`.
- [ ] **Step 5:** Milestone skill section 3: `kvizotron-browser-walkthrough` (export page desktop + mobile, a CSV opened in LibreOffice: columns split, diacritics), `kvizotron-check-applied`, fresh whole-branch review.

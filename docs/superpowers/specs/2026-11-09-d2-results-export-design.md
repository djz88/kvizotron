# D2 Export — design

Milestone D2 of [roadmap.md](../../_architecture/roadmap.md). Finishes `FR-42` (results, participants,
statistics) and `FR-44` (Google Sheets contract only), [providers/csv-io.md](../../_architecture/providers/csv-io.md).

Marks: **[user]** said by the user, **[docs]** already in `docs/_architecture`, **[call]** the
designer's choice, open to correction.

## Why

After a run an organiser needs its data outside Kvízotron: to archive and process results in a
spreadsheet (marks, sorting), to contact winners and hand over rewards, to analyse which questions were
hard, and as evidence for a sponsor or a school of how the contest went **[user]**. Today the only way
out is reading the admin pages; only questions can be exported (B5).

## Goals

- Export the data of one run, of all runs of a quiz, or of runs picked on the run comparison **[user]**.
- Six CSV files, each downloadable on its own, and a "download all" ZIP **[user]**:
  attempts, participants, question statistics, answers, reward entitlements, draw history.
- Answers one row per attempt × question **[user]**.
- Participant photos optionally inside the ZIP, a checkbox on the export page, ticked by default
  **[user]**. Not a setting **[user]**.
- Opens correctly by double click in Czech Excel: semicolon delimiter, UTF-8 with BOM **[user]**.
- Column headers and question texts in the admin's UI language **[user]**.
- Formula-injection protection on every cell **[docs]** (FR-42, AC-52).
- Prepared in the background, then downloaded; a link valid 24 hours **[user]**.
- A `SpreadsheetExporter`-style port for Google Sheets with no real connector **[docs]** (FR-44).

## Non-goals

- A presentation view of results (projector, print, PDF) — later **[user]**.
- A Google Sheets / Workspace connector **[docs]** (overview, roadmap "LATER").
- JSON export **[docs]** (ADR-0032, LATER as a module).
- Import of result files **[call]**: these CSVs are output only.
- A separate `jobs` container **[user]**; it stays planned for D3.
- A setting for photos in the export **[user]**.
- Scheduled or e-mailed exports **[call]**.

## Anti-goals

- An export that contains data the run's data profile does not keep, or that outlives what retention
  allows **[docs]** (csv-io.md "Exports must not bypass retention").
- A cell starting with `=`, `+`, `-`, `@`, tab or carriage return that a spreadsheet would run **[docs]**.
- PII leaving the application without an audit record of who exported what **[docs]** (ADR-0014).
- An answer key, an access-code hash or an attempt token in any file **[call]**.
- A download link another admin or an anonymous visitor can use **[call]**.
- A request that blocks the only gunicorn worker for the length of a big ZIP **[user]** (background).

## Behaviour

### Where it starts

- Run page: a tab **Export** for that run **[user]**.
- Quiz: an **Export results** action covering all runs of the quiz **[user]**.
- Run comparison (runs page, table from `run_stats.comparison`): checkboxes per run and **Export
  selected** **[user]**.
- All three lead to one page `/admin/exports/new?quiz=<id>&runs=<id,…>` **[call]** with the choices
  below. The existing `/admin/export` (questions, B5) stays as it is **[call]**.

### Export page

- Lists the chosen runs (name, status, data profile) **[call]**.
- Offers one row per file with a checkbox, and only files that at least one chosen run can provide
  **[call]**. A file no chosen run can provide is not shown; a file only some runs provide says so
  ("2 of 3 runs") **[call]**.
- Checkbox **Include photos** shown only when the ZIP is chosen and a chosen run holds photos, ticked by
  default **[user]**. Without it the answers file still names the photo (`photo: <file name>`)
  **[user]**.
- Two buttons: **Download chosen files separately** and **Download all as ZIP** **[user]**.
  "Separately" prepares the chosen CSVs in one job and offers one link per file; "ZIP" one link
  **[call]**.
- When a chosen file contains personal data (names, e-mails, nicknames, answers, draw winners), a
  confirmation checkbox "This export contains personal data" must be ticked before submit; without it
  the form is refused with 400 and a message **[user]**.
- Below the form: this admin's export jobs from the last 24 hours with status and links **[call]**.

### What each file holds, by data profile

Data profile values per [ADR-0050](../../_architecture/adr/0050-data-profile-and-local-resume.md)
**[docs]**. Each row of every file carries `run` (run name) and `revision` (number) so a quiz-wide export
across revisions stays readable **[call]**.

| File | Columns (meaning) | `none` | `score` | `answers` | `detailed` |
|---|---|---|---|---|---|
| attempts | attempt id, participant (nickname / name per run rules), status, score, max, percent, submitted at, official yes/no, place | — | yes | yes | yes + duration |
| participants | participant id, nickname, name, e-mail, attempts count, best score | — | yes | yes | yes |
| question statistics | question no, question text, type, answered, correct share, average points, max points | count of submitted attempts only (one row per run) | yes | yes | yes |
| answers | attempt id, question no, question text, answer as text, points, max, graded by (auto / admin) | — | only answers kept for grading (photos) | yes | yes |
| reward entitlements | rule, reward, participant, nickname, e-mail, reason (threshold / participation / manual / draw), state, handed over at, cancel reason | — | yes | yes | yes |
| draw history | rule, draw no, kind (draw / redraw / move up / substitute), at, admin, eligible count, fingerprint, winners, alternates, reason | — | yes | yes | yes |

- `none` keeps no row per attempt **[docs]**, so only the per-run count of submitted attempts is
  exportable **[call]**.
- Times are in the installation's configured time zone, ISO 8601 with offset **[call]**.
- Numbers use a decimal comma when the admin's language is cs or uk, a point for en, so Excel in that
  locale reads them as numbers **[call]**.
- Answer text comes from the question type plugin (a new method on the contract, e.g.
  `answer_as_text(question, answer, locale)`) so matching pairs, numbers and choices read as words,
  not JSON **[call]**.
- Draw winners are written as nickname and participant id; e-mail only in entitlements **[call]**.
- Unsubmitted attempts are left out of every file **[call]**; test-link attempts too **[call]**.
- Archived runs can be exported **[call]**.

### CSV format

- Delimiter `;`, UTF-8 with BOM, CRLF line ends, every field quoted when it contains `;`, `"` or a line
  break **[user]** / **[call]** for line ends.
- First row: headers translated to the admin's language at the moment the job is created **[user]**.
  Question texts in the same language, falling back to the quiz's first language **[call]**.
- Formula-injection protection as for question export: a cell starting with `=`, `+`, `-`, `@`, tab or
  CR gets a leading `'` **[docs]**. Negative numbers written as numbers are exempt only if the column is
  numeric and the value parses as a number **[call]** (else "-3" would show as text).
- File names: `<quiz-slug>-<run-or-all>-<file>-<YYYYMMDD-HHMM>.csv`, ZIP the same with `.zip`
  **[call]**.

### Photos in the ZIP

- Under `photos/<run>/<attempt id>-<question no>.<ext>`, answers file names that path **[call]**.
- Only photos the profile keeps **[docs]**. Size of the ZIP is bounded by the existing 2 GB per run
  limit (ADR-0028) **[docs]**; the ZIP is streamed to disk, never held whole in memory **[call]**.

### Background job

- Submit creates an `export_job` row (`queued`) with admin, kind, runs, files, photos flag, language
  and `expires_at = created + 24 h`, then starts a daemon thread in the app process and redirects to
  the export page **[user]**.
- The thread sets `running`, writes the files under `exports/<job id>/` on the media volume (never
  served directly), then `done`, or `failed` with a short error code in `report_json` **[call]**.
- At most one running export per admin and two in the whole app; a third waits as `queued` and is
  started by the next submit or page load when a slot frees **[call]**.
- The page polls the job status with HTMX every 2 s while a job is `queued` or `running` **[call]**.
- On app start, and on every export page load, jobs left `running` or `queued` by a previous process
  become `interrupted` and can be started again with one button **[user]** (restart = interrupted).
- Download `GET /admin/exports/<job id>/<file>` only for the admin who created the job, only while
  `done` and not expired; else 404 **[call]**. Sent with `Content-Disposition: attachment` and
  `Cache-Control: no-store` **[call]**.
- Cleanup: every export submit and every load of the export page deletes the files and rows of jobs
  past `expires_at` **[user]**. No background timer **[user]**.

### Audit

- Every job records `export.created` with admin, runs, files, photos flag, whether PII is included
  **[docs]** / **[call]** for the fields; every download records `export.downloaded` **[call]**.
  No PII values in the audit **[docs]**.

### Google Sheets contract (FR-44)

- A port in `app/contracts/` that takes the same table structure (named sheets of columns and rows) and
  returns where it went, registered like other exporters **[call]**.
- No real implementation; a test-only fake passes the shared contract tests **[docs]** / **[call]**.
- The CSV writer implements the same table structure so the export domain code does not care which
  target it writes to **[call]**.

## Constraints

- New code in a provider/plugin behind a contract, not in the kernel **[docs]** (ADR-0037). The export
  domain logic (what rows a run gives) in `app/domain/`, file writing in `app/providers/csv_io/`
  **[call]**.
- Score, places and statistics come from the same domain functions the admin pages use
  (`run_stats`, scoreboard, `results`), never recomputed differently **[call]**.
- One gunicorn worker with threads **[docs]** (architecture.md); the export thread must not hold a DB
  write lock for long — read in chunks, write files outside transactions **[call]**.
- SQLite WAL: the thread opens its own DB connection and closes it at the end **[call]**.
- `export_job` matches data-model.md (`id`, `admin_id`, `kind`, `status`, `report_json`, `created_at`,
  `expires_at`) **[docs]**; the job's choices go in `report_json` or new columns, builder's choice.
- No new dependency **[call]** (`csv`, `zipfile`, `threading` from the standard library).
- `app/domain/models.py`, migrations, contracts and manifests are always VELKÁ in the dev-workflow
  profile **[docs]**.

## Risks

- A thread dies with the process; covered by `interrupted` and restart **[user]**.
- Large ZIP fills the media volume; bounded by 24 h expiry and per-admin limit **[call]**.
- Excel locale differences (decimal separator) still bite users with a non-matching OS locale;
  accepted **[call]**.
- Plugin `answer_as_text` must exist on every question type, so the contract tests grow **[call]**.
- Quiz-wide export of many runs is slow on SQLite; acceptable at ~50 participants per run
  **[call]**.

## Left to the builder

- Exact names of the port, the new contract method and URL paths.
- Whether `export_job` choices are columns or `report_json`.
- Layout of the export page and the job list, within the existing admin look and Basic / All panel.
- The exact HTMX polling and the "start again" control.
- The translation strings (cs, uk filled).

## Verification

New AC rows from **AC-101**, each named by a test **[docs]** (`tests/test_docs.py`). Proposed:

- AC-101 Export page offers only the files the chosen runs' data profiles allow; `none` gives only counts.
- AC-102 Every CSV is `;`-separated UTF-8 with BOM, headers in the admin's language, no cell starts with a formula character.
- AC-103 Answers file has one row per submitted attempt × question with answer text from the plugin.
- AC-104 ZIP with photos holds every kept photo and the answers file names its path; without the box it holds none.
- AC-105 A job runs in the background, the page shows progress, a download works for its creator only and is gone after 24 h.
- AC-106 A job left running by a restart shows as interrupted and can be started again.
- AC-107 PII export needs the confirmation and leaves `export.created` and `export.downloaded` audit records without personal values.
- AC-108 Quiz-wide and selected-runs exports carry run and revision on every row.
- AC-109 The Sheets port has a test fake passing the shared contract tests.

Plus an ADR (next free number, **ADR-0055**) for the in-process background export job and the CSV
dialect choice **[call]**, `make quality`, `make smoke`, a browser walkthrough of the export page and
opening a file in LibreOffice to check columns and diacritics.

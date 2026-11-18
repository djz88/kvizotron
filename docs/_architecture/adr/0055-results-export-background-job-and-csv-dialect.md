---
status: accepted
date: 2026-11-09
---

# ADR-0055: Results export as a background job in the app process, a semicolon CSV dialect, and a table port for Google Sheets

## Context and Problem Statement

`FR-42` asks for an export of results, participants and statistics with formula-injection protection, and `FR-44` for a Google Sheets contract without a connector. An organiser needs the data of one run, of every run of a quiz or of runs picked on the comparison, opened by double click in a Czech spreadsheet, with photos if they want them. Open were where the files are prepared (a request, a thread or the planned `jobs` container of D3), how a job that dies with the process is recognised, how many jobs may run at once, which CSV dialect is used, how numbers escape formula protection, which place and official attempt the files name, and how the Sheets contract relates to the CSV writer.

## Decision Drivers

* One gunicorn worker serves every request ([architecture.md](../architecture.md)); a big ZIP must not block it
* No scheduler and no new container before D3; no new dependency
* Czech Excel opens a file by double click only with `;` and a byte order mark
* A cell that starts with `=`, `+`, `-`, `@`, tab or CR must not run as a formula ([AC-52](../acceptance-criteria.md)), yet a negative score should stay a number
* A file says the same as the admin pages: places, the official attempt and statistics come from the same domain functions
* PII leaves the application only for the admin who asked, with an audit record and no values in it ([ADR-0014](0014-local-admin-auth-argon2id-equal-roles.md))

## Considered Options

* A daemon thread in the app process, jobs in `export_job`, a per-process boot token
* Building the files in the request
* A separate `jobs` container now

## Decision Outcome

Chosen option: "A daemon thread in the app process, jobs in `export_job`, a per-process boot token", because it keeps the request short without a new container, and the container planned for D3 can take over the same table and port later.

Rules:

* **Ports.** `ResultsExporterProvider` (port `results_exporter`, implemented by `csv_io` as `csv`) keeps jobs and their files: `create`, `job`, `jobs`, `claim_next`, `write`, `fail`, `restart`, `path`. `TableSinkProvider` (port `table_sink`) takes the same `ExportTable` values (`name`, `columns`, `headers`, `rows`, `numeric`) and returns where they went; it is the Google Sheets contract. No module implements it; a test fake passes the shared suite in `tests/contracts/`. The domain (`app/domain/results_export.py`) builds the tables and does not care which port writes them.
* **Job.** A submit stores an `export_job` row (`queued`) with the choices (quiz, runs or all runs, files, photos, bundle, locale, file name) in `choices_json` and `expires_at` 24 hours later, records `export.created`, and calls `export_runner.kick()`. `kick()` loops `claim_next()` and starts a daemon thread for each job it returns. `claim_next()` returns the job it set `running`, with its choices, or `None`; the thread therefore needs no in-memory map of jobs to admins. The thread writes the files under `exports/<job id>/` on the media volume (directory `0750`, each file created `0640`), which no route serves directly, sets `done` with the file names in `report_json`, or `fail(job, "error")` and logs only the job id. Both change only a `running` job; a job restarted or expired meanwhile keeps no files. The submit stores the job and its `export.created` record in one transaction and kicks after it commits. Its last step closes its database connection, after the `kick()` that starts the next job.
* **Slots.** At most one running job per admin and two in the application, checked inside the `IMMEDIATE` transaction of `claim_next()`. A job without a slot stays `queued` and starts on the next submit, page load, poll or the end of another job. A thread that cannot start marks its job `failed`, so the slot is freed.
* **Interrupted.** Each process has a random `BOOT` token stored on the job. A `queued` or `running` job of another boot becomes `interrupted` when the export page, its job list or a new job is loaded or created, and when a job is claimed; not at application start, which keeps the provider free of startup hooks. Until someone opens the page, a dead job still shows `running`. "Start again" is offered only for `interrupted` and `failed` jobs: it creates a new job with the same choices and deletes the old row; any other job answers 404.
* **Cleanup.** The same calls delete rows and files of jobs past `expires_at`. No timer.
* **Download.** `GET /admin/exports/<job>/<name>` only for the admin who created the job, only while it is `done`, unexpired and names that file; else 404. Sent as an attachment with `Cache-Control: private, no-store`, and recorded as `export.downloaded` with the file name.
* **CSV dialect.** UTF-8 with a byte order mark, `;` as delimiter, CRLF line ends, fields quoted by Python's `csv` when they contain `;`, `"` or a line break. Headers and question texts in the admin's language at the time the job was created, question texts falling back to the quiz's default language. Numbers with a decimal comma for cs and uk, a point for en; times ISO 8601 with the offset of the configured time zone.
* **Formula protection.** Every cell, headers included, goes through the same `protect` as the question export (a leading `'` before `=`, `+`, `-`, `@`, tab, CR). Only a value in a column the table lists in `numeric` that fully matches `^-?\d+([.,]\d+)?$` (ASCII digits) is written as it is, so `-3` stays a number and `-3+1` does not.
* **What a run gives.** `offered` lists only files that some chosen run provides under its data profile ([ADR-0050](0050-data-profile-and-local-resume.md)): under `none` only question statistics with the count of submitted attempts; answers when the profile keeps every answer or a revision has a photo question; entitlements only with reward rules, draws only with a draw rule. Unsubmitted attempts, test runs and test-link attempts never appear. Every row starts with `run` (the run number) and `revision` (the revision number; the `none` row names the run's current revision).
* **Place and official.** `place` is the rank of the attempt in the admin board (`results.board(run, audience="admin")`), which ignores public visibility and keeps the run's revision mode; `BoardRow.attempt_id` ties a row to its attempt. `official` is `results.official_attempt(participant)`, the attempt rewards and draws count, which follows the run's revision mode (addendum of 2026-11-17 to [ADR-0053](0053-rewards-tiers-alternates-and-draw-history.md)); an attempt without a participant is official on its own when the mode counts it. Under `latest` an attempt on an older revision has neither a place nor `official`.
* **Answer text.** The question type's existing `summarize` in the admin's language; no new contract method. A photo is written as `photo: photos/<run no>/<attempt id>-<question no>.webp`, whether or not the ZIP holds it.
* **Photos.** The checkbox "Include photos" is shown, ticked, whenever a chosen run keeps photos; the page has no JavaScript and no state for "ZIP chosen", so its hint says "only in the ZIP" and the server ignores it for separate files and for a ZIP without the answers file, which is what names the photos. Missing photo files are skipped. The ZIP is written to disk entry by entry.
* **Personal data.** Every file except question statistics is personal, and so are photos in the ZIP; choosing either needs the confirmation box, otherwise 400. The audit records hold quiz, run ids, files, the photos flag and whether personal data were included, never a value from a row.
* **File names.** `<quiz slug>-<run-N|all|runs>-<YYYYMMDD-HHMM>` as a prefix: `<prefix>-<file>.csv` for separate files and inside the ZIP, `<prefix>.zip` for the ZIP. The provider refuses a prefix outside `[A-Za-z0-9][A-Za-z0-9._-]*`.

### Consequences

* Good, because the only worker stays free while a file is written, without a new container
* Good, because files show the same places, official attempts and statistics as the admin pages
* Good, because a Sheets connector can be added later as a module behind `table_sink` without touching the domain
* Bad, because a thread dies with the process; the job becomes `interrupted` only when someone opens the page, and must be started again by hand
* Bad, because the thread competes with requests for the single SQLite writer while it marks the job
* Bad, because the decimal comma follows the admin's language, not the spreadsheet's locale

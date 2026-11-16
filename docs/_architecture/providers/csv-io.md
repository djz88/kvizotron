# Provider: CSV import/export

| | |
|---|---|
| Contract | `ImporterProvider`, `ExporterProvider`, `ResultsExporterProvider` |
| Package | `app/providers/csv_io/` |
| Stage | B (import, export of questions), D (export of results) |
| Decision | [ADR-0019](../adr/0019-csv-import-export-json-in-field-draft-output.md), formats: [ADR-0032](../adr/0032-csv-schema.md), [ADR-0045](../adr/0045-csv-one-file-and-failed-images.md), results export: [ADR-0055](../adr/0055-results-export-background-job-and-csv-dialect.md) |

## Requirements

- `FR-40` CSV import of **individual questions, question banks and complete quizzes**, including
  configuration and translations. Media can be attached separately or referenced by URL.
- `FR-41` Complex question structures have a defined CSV schema and/or JSON stored in a CSV field.
  Import must offer column mapping, preview, validation, per-row error list and optional dry-run. The
  import output is a new draft, never an automatically published revision.
- `FR-42` Export of quizzes (CSV per supported schema), results, participants and statistics. CSV data
  must be correctly escaped and protected against CSV formula injection when opened in a spreadsheet.
  PII export only for authorised admins.
- `FR-44` A plugin contract for export to Google Sheets/Workspace will be prepared; **connector
  implementation is not required for v1.0**.

## Behaviour

- An "authorised admin" (FR-42) is any logged-in admin; every PII export is audited
  ([ADR-0014](../adr/0014-local-admin-auth-argon2id-equal-roles.md)).
- Import removes the protective character added against formula injection, so export followed by
  import gives the same data ([ADR-0032](../adr/0032-csv-schema.md)).
- Two outputs: a human overview CSV (no answer keys, no e-mails, not importable) and a full CSV used for
  both export and import. A JSON export is LATER, as a separate module.
- Media referenced by URL are never confused with local files ([AC-13](../acceptance-criteria.md)).
- Exports must not bypass retention rules ([../../privacy.md](../../privacy.md)). When a run's data are deleted, `delete_for_runs` removes the jobs and files naming that run or all runs of its quiz; a queued or running job ends as failed with `run_data_deleted`, and its later write is refused ([ADR-0056](../adr/0056-retention-job-summary-held-runs.md)).
- Imports tracked in `import_job` with `expires_at`. The uploaded file waits in `imports/` on the media volume, which is never served.
- Reading files is this provider's job, and what a row means is the domain's (`question_import.py`) and the question type's. Columns: `sample/csv-format.md`.

## Results export (D2)

Decision: [ADR-0055](../adr/0055-results-export-background-job-and-csv-dialect.md).

- Ports: `ResultsExporterProvider` (port `results_exporter`, id `csv`, `app/providers/csv_io/results.py`) keeps jobs and files; `TableSinkProvider` (port `table_sink`) is the Google Sheets contract (FR-44), with only a test fake (`tests/support/sheets_fake.py`). Both take `ExportTable` values built by the domain (`app/domain/results_export.py`).
- Jobs live in `export_job` ([data-model.md](../data-model.md)), files under `exports/<job id>/` on the media volume, which is never served; a file goes out only through `path()`, which checks the admin, the status `done`, the expiry and the file name.
- Statuses, slots (`limits.EXPORT_SLOTS_PER_ADMIN`, `EXPORT_SLOTS_TOTAL`), tidying of expired and interrupted jobs (`BOOT`), restart, link lifetime (`limits.EXPORT_LIFETIME`), the CSV dialect (`writer.write_table`), file modes and file names: [ADR-0055](../adr/0055-results-export-background-job-and-csv-dialect.md). Code: `CsvResultsExporter` in `results.py`, `writer.py`, `limits.py`.
- The background thread, the page and the audit are in the API and domain: [modules/api-ui.md](../modules/api-ui.md), [../../privacy.md](../../privacy.md).

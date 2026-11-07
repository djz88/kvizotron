# Provider: CSV import/export

| | |
|---|---|
| Contract | `ImporterProvider`, `ExporterProvider` |
| Package | `app/providers/csv_io/` |
| Stage | B (import, export of questions), D (export of results) |
| Decision | [ADR-0019](../adr/0019-csv-import-export-json-in-field-draft-output.md), formats: [ADR-0032](../adr/0032-csv-schema.md), [ADR-0045](../adr/0045-csv-one-file-and-failed-images.md) |

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
- Exports must not bypass retention rules ([../../privacy.md](../../privacy.md)).
- Imports tracked in `import_job` with `expires_at`. The uploaded file waits in `imports/` on the media volume, which is never served. `export_job` comes with D2.
- Reading files is this provider's job, and what a row means is the domain's (`question_import.py`) and the question type's. Columns: `sample/csv-format.md`.

# Module: app/providers

Infrastructure chosen by the operator, changed only by a restart: `auth_local/` (login, CLI for admins), `persistence_sqlite/` (database settings), `media_local/` (images on a volume), `csv_io/` (reading and writing CSV and ZIP), `retention/` (deletion records). Features are in `app/plugins/`.

## Responsibilities

- `auth_local`: Django backend, `init_admin`, `reset_admin_password`, `passwords.read_password`. The commands `createsuperuser` and `changepassword` deliberately just refuse to work.
- `persistence_sqlite`: `database_settings()` with WAL and `transaction_mode: IMMEDIATE`, `healthcheck()`.
- `media_local`: checking and downscaling images, the `media_asset` table. The file content decides, not its name. `private_assets_older_than` provides private photos for the cleanup of the hourly pass. `remote.py` downloads from addresses and refuses the internal network (ADR-0043), `media_address_check` holds the results of the hourly check.
- `csv_io`: the import file lies between the steps in `imports/` on the media volume, the results export in `exports/<job id>/` (table `export_job`, the link is valid for 24 hours, `path()` verifies the admin; a job of another process is recognised by `BOOT` and marked `interrupted`, `claim_next()` guards 1 running job per admin and 2 in the app, ADR-0055), a ZIP is never extracted to disk, cells are protected against formulas on write and restored on read. What a row means is handled by the domain and the question types. `delete_for_runs` removes, after a run's data is deleted, the jobs and files that name it or take all runs of the quiz.
- `retention`: the `retention_job` table with deletion records: counts, never a personal value; it does not return the e-mail fingerprint. What to delete and when is handled by the domain.
- Every provider lists the `settings` field in its manifest, even an empty one (ADR-0042).

## Forbidden

- Importing from `app/domain`, `app/api`, `app/plugins`.
- Disabling a provider at runtime: `lifecycle` refuses it.
- A password as a command argument: it is visible in `ps` and the history. Only `--password-stdin` or a terminal prompt.
- `set_password` without `read_password` or `validate_password`. `AdminUserManager.create_admin` does not validate, the caller does.

## Public API

Only through the manifest and the protocols `AuthenticationProvider`, `PersistenceProvider`, `MediaStorageProvider`, `ImporterProvider`, `ExporterProvider`, `ResultsExporterProvider`, `RetentionProvider`. Tests: `tests/contracts/`, `tests/providers/`.

Media: a participant's photo is private (`private`), only PNG, JPEG and WebP, rebuilt from pixels. `/media/<id>` answers 404 for it and only a route that verifies the right serves it (ADR-0047).

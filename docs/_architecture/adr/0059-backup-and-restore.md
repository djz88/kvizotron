---
status: accepted
date: 2026-11-10
---

# ADR-0059: A daily verified backup from the `jobs` service and a manual restore that keeps what it replaces

## Context and Problem Statement

Everything the application stores lives in one SQLite file and a media directory, on two volumes. [deployment.md](../../deployment.md) and [privacy.md](../../privacy.md) already required a backup made with SQLite's own mechanism, a limited retention, and a restore that has been tried. Nothing made one. A backup that is never verified is a hope, a restore that overwrites live data in place can lose it, and backups that outlive a deletion bring personal data back.

## Decision Drivers

* A copy of a live SQLite file in write-ahead mode is not consistent; a writer must neither be stopped nor starved by the backup
* A backup counts only when it is complete and verified, and a failed or killed one never replaces a good one
* A restore must be able to fail safely and keep the data it replaces
* Retention of backups is a privacy requirement ([FR-34](../../privacy.md)), so it is not skipped when a backup fails
* Files restored by root make `migrate` fail with `unable to open database file`; the application runs as uid 1000
* No new service, no new dependency, no administration page (visibility of the jobs loop came with [ADR-0061](0061-heartbeat-and-restore-marker.md))

## Considered Options

* A backup by copying the files, or by SQLite's online backup API
* Scheduling: the existing `jobs` service; a cron on the host; a new service
* Restore: in place; into a side directory that replaces the data; through the administration
* A provider for backups, or a domain module next to `jobs`

## Decision Outcome

Chosen: `app/domain/backup.py`, run daily by the `jobs` service into a `backups` volume that only `jobs` mounts, and `manage.py backup` and `manage.py restore` for the operator. A provider would be a new architecture for a fixed single implementation; `jobs` and the commands already sit in the domain ([ADR-0056](0056-retention-job-summary-held-runs.md)).

### Making a backup

* A pass of `jobs` runs every hour. It makes a backup when no complete one exists for the current local date, so one per day, the first at start. A second one on the same date replaces the first once it has verified. `manage.py backup` makes one by hand, with the same rules.
* A backup is a directory `backups/YYYY-MM-DD/` with `db.sqlite3`, the files under `media/` and `manifest.json` (creation time, applied migrations, size and sha256 of every file). It is built as `.tmp-<date>`, so a directory with a date for a name is complete and a killed run leaves only a `.tmp-*` that nothing lists.
* The database is copied with the SQLite backup API in steps of 100 pages, never as a file, so writers go on. A writer committing between steps restarts the copy, so the copy has a 300-second deadline and a backup that misses it is given up and retried at the next pass.
* Media files that the previous backup holds unchanged (same path, size and checksum) are hard-linked, after the file in that backup has itself been checked against its manifest entry (a damaged or missing one is copied from the live file, so one bad file never stops later backups); the rest are copied, also when linking fails. The directories `exports/` and `imports/` directly under the media root hold results exports (e-mails and every photo of a run) and uploaded imports, which the application removes within 24 hours ([privacy.md](../../privacy.md#backups)): they are not backed up, and neither are the temporary files of uploads in progress. Every backup is complete on its own, and deleting old ones frees a file when the last backup that refers to it goes.
* Before the directory gets its date, it is verified (`PRAGMA integrity_check` on the copy, every checksum of the manifest, no migration that the installed code does not know) and every file and directory is written to disk (`fsync`), so a power cut leaves no dated directory that is only partly on disk. One backup runs at a time: `create`, `prune` and `restore` share a file lock.
* Any failure removes what was built, is logged by exception type only (a message can hold a path or a value) and becomes a `BackupError` with a fixed text. The previous backups are untouched.

### Retention

* `KVZ_BACKUP_RETENTION_DAYS` (default 30). `prune` deletes dated backups older than that, `pre-restore-*` directories older than that by modification time, and leftovers of killed runs after a day.
* `prune` runs after every backup attempt, including a failed one. Backups hold personal data, so their retention must not wait for a good day; a full disk is also the likeliest reason for a failure, and pruning frees it. It always keeps the newest backup that still verifies, however old or however far the clock is ahead, so pruning can never leave the installation without a backup. When none verifies, it keeps the newest by date.
* The retention pass and the backup are independent in the `jobs` pass: a failure of one does not stop the other.

### Restoring

`docker compose -f deploy/compose.yaml run --rm --no-deps jobs python manage.py restore <YYYY-MM-DD|latest>` with `caddy`, `app` and `jobs` stopped (`docker compose -f deploy/compose.yaml stop caddy app jobs`).

* It verifies the chosen backup first and refuses a damaged one. `latest` is the newest complete backup and never falls back to an older day when it is damaged: the operator names a date, so that going back in time is a decision.
* It refuses a backup of an older schema (one that lacks a migration of the installed code), which would be half-applied: restore it with the matching version, or migrate it on purpose. A backup with more migrations than the code knows is refused when it is made and when it is restored.
* It refuses while a connection to the database is open at that very moment: `BEGIN EXCLUSIVE` on the live file with a short wait, and after its own connection is closed any `-wal` or `-shm` file that is still there (in write-ahead mode an idle reader neither blocks the lock nor is blocked by it, but SQLite removes both files when the last connection closes). This check sees a request or a pass in flight, but it cannot see a running but idle `app` or `jobs`, whose connections close after every request or pass (`CONN_MAX_AGE` 0). So the restore also refuses while the heartbeat file of `app` or of `jobs` beside the database is younger than 60 seconds, and says which service and how long to wait ([ADR-0061](0061-heartbeat-and-restore-marker.md)). Stopping `caddy`, `app` and `jobs` before the restore stays the operator's job.
* It copies the current database files and media into `pre-restore-<time>` in the backups volume first, then replaces the contents of the database file and the media directory (never the directories, which are mount points, and never the transient `exports/` and `imports/` directories of the media, which it neither stashes, clears nor replaces), always with copies and never with links, because media files share inodes with other backups and a write through a link would change them. The new database is staged and fsynced before the old log is removed.
* It checks the restored database and every checksum, gives files to uid 1000 when it runs as root (in the compose `jobs` container it already is uid 1000, so the files are its own), warns when files are not owned by uid 1000 or by the owner of the data directory, and prints what it restored and where the previous data is.
* When anything fails after the stash, it puts the previous data back and says so; when that fails too, the message names the newest `pre-restore` directory.
* After the stash is complete and before anything live is replaced it writes a marker, `.restoring`, in `pre-restore-<time>`, and removes it when the installation or the putting back succeeded. A restore refuses while any marker exists, and `prune` never deletes a marked directory ([ADR-0061](0061-heartbeat-and-restore-marker.md)).
* `pre-restore-*` is pruned like a backup, so it does not keep personal data beyond the retention either.
* A restore interrupted by a kill leaves its marker. The operator recovers from the directory that the refusal names ([deployment.md](../../deployment.md#restore)).

### What an operator must know

* A restore brings back what the backup held. The next retention pass deletes runs past their period again, except runs that the backup still holds as held ([ADR-0056](0056-retention-job-summary-held-runs.md)), which an admin confirms on the Deletion history page. An erasure request or a "Delete data now" done after the backup date comes back and must be repeated ([privacy.md](../../privacy.md#backups)). No redaction of backups was added.
* After a provider is switched through `KVZ_PROVIDER_*`, the old provider's rows in `django_migrations` are unknown to the code and every backup fails the migration check until they are removed (or the old provider is installed again). The failure shows in the `jobs` log.
* A failed backup shows only in the `jobs` log (`docker compose -f deploy/compose.yaml logs jobs`), and the Deletion history page shows the outcome of the last pass as a whole ([ADR-0061](0061-heartbeat-and-restore-marker.md)).
* A manual `manage.py backup` on a date that already has a backup replaces it, so before an upgrade copy today's backup directory (or make the pre-upgrade backup on the day before) if you want to be able to go back to it.
* A backup on the same machine does not survive its loss. Copying the `backups` volume off the machine is the operator's job.

### Consequences

* Good: a backup that exists is complete, verified and on disk, and prune cannot remove the last good one.
* Good: a restore cannot destroy live data without a copy beside it, and is tested for refusals, a failure halfway, ownership and links.
* Good: nothing new to install and no new table; no migration.
* Bad: a backup holds all personal data for up to the retention, and a restore can bring deleted data back until it is repeated.
* Bad: a hard-linked backup shares media with the others, so the fallback copy needs space for a full second copy.
* Bad: a failed backup is visible only in a log, and a prune that cannot delete a directory logs it and makes the manual `backup` command exit non-zero, but does not fail the pass of `jobs` ([ADR-0061](0061-heartbeat-and-restore-marker.md)).

### Confirmation

`tests/domain/test_backup.py`, `test_restore.py` and `test_jobs_backup.py` ([AC-134](../acceptance-criteria.md) to [AC-137](../acceptance-criteria.md); the heartbeat refusal, the marker and the result of `prune` are [AC-143](../acceptance-criteria.md) and [AC-145](../acceptance-criteria.md)); `make load` restores a backup after the live data was changed and compares rows and photo checksums ([AC-139](../acceptance-criteria.md)).

## More Information

Settings: [configuration.md](../../configuration.md#backups). Procedure: [deployment.md](../../deployment.md#backup-and-restore). Related: [ADR-0015](0015-docker-compose-caddy-systemd-alt.md), [ADR-0056](0056-retention-job-summary-held-runs.md).

Refined by [ADR-0061](0061-heartbeat-and-restore-marker.md): the heartbeat refusal, the marker of an interrupted restore and the result that `prune` returns.

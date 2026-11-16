---
status: accepted
date: 2026-11-10
---

# ADR-0061: Heartbeat files and a pass record, a marker for an interrupted restore, and an address key for the erasure search

## Context and Problem Statement

[ADR-0059](0059-backup-and-restore.md) and [ADR-0056](0056-retention-job-summary-held-runs.md) left gaps that were recorded as technical debt before the tag `v1.0.0`:

* The `jobs` healthcheck was `true`, so a stuck loop was invisible, and nothing on a page said whether the last pass worked (TD-068).
* `restore` saw only a connection that was open at that very moment. A running but idle `app` or `jobs` closes its connections after every request or pass, so a restore beside them was accepted and could lose submissions made between its stash and its placement (TD-089).
* A restore killed halfway left a half-replaced database beside a `pre-restore-<time>` directory with nothing that said so, and a second restore stashed the half state as the newest `pre-restore` (TD-082).
* A `prune` that could not delete a directory logged it, and `manage.py backup` still exited 0 (TD-085).
* The erasure search by e-mail loaded every participant that has an address and compared in Python, and an erased nickname could stay on a public scoreboard for up to 5 seconds (TD-076).

Smaller fixes of the same change need no decision: a hand-crafted result photo address no longer logs its token (TD-021), no photo file is left behind when a later photo of the same submission fails (TD-015), and the record of a purge is more accurate (TD-072). The tests and contract suites of deletion were completed (TD-074, TD-075).

## Decision Drivers

* A restore must refuse beside a live service without a way to fool it for ever: a crash must not block it for good
* A restore must not refuse falsely, nor send the operator to a directory that is incomplete
* The only thing that may block without an age is a marker of data that need a human decision
* A heartbeat must never slow down or fail a request or a pass
* The healthcheck of `jobs` must not mark a `jobs` unhealthy that is working through a long backup
* No new service, no new dependency, no new setting, and the application does not read the volume of backups
* Logs carry counts and exception types, never a path, an address or a name

## Considered Options

* Liveness of `app` and `jobs`: a file beside the database that each touches; a row in the database; a lock held for the whole life of the service; the Docker API
* A marker of an interrupted restore: a file in the `pre-restore` directory; a file beside the live database; nothing and a longer recovery text
* Finding addresses: an HMAC fingerprint of the address in a column; the address stripped and casefolded in an indexed column; a search in Python as before

## Decision Outcome

### Heartbeat files and the pass record

`app/domain/heartbeat.py` writes one hidden file per service, `app` and `jobs`, beside the database file (`/data/db` in Compose); its modification time is the heartbeat. A second file there holds the record of the last hourly pass: when it started, when it finished and how it ended (`ok`, `failed` or `stopped`). With an in-memory database every function does nothing, writing never raises, and a missing or broken file reads as nothing. The reading side uses only the standard library, so a healthcheck can call `python -m app.domain.heartbeat check` without a database and without the network.

* `jobs` touches its file every 15 seconds from a daemon thread and removes it on a clean stop.
* `app` touches its file from a middleware that sits last in the list, at most once every 10 seconds per process, on every request including `/healthz` (the image's check calls it every 10 seconds, so an idle `app` stays recent). A failed write is swallowed and logged by exception type. The file is removed at a clean exit of the process where that is cheap (`atexit`); otherwise it goes stale.
* A heartbeat counts as alive while it is younger than 60 seconds, which is more than the write intervals and the healthcheck. A crash blocks a restore for at most that long, and the refusal says how long.
* The pass record is written when a pass starts (it keeps the previous finish and outcome until the pass ends) and when it ends. A pass is `failed` when the retention pass, the backup or the prune raised, `stopped` when nothing raised but the service was stopping (SIGTERM) before the backup, which then does not start, and `ok` otherwise, also when no backup was due. A prune that leaves directories behind does not make the pass `failed`: the pass logs the count as a warning, and the exit code of the manual `backup` command is the signal ([AC-145](../acceptance-criteria.md)).
* The `jobs` healthcheck in `deploy/compose.yaml` runs the check command every 60 seconds (10 seconds to answer, 60 seconds to start, three tries). It fails when no pass is running and the last one finished more than 7200 seconds ago, or when a pass is running (its start is newer than the last finish, or there is no finish) and started more than 3600 seconds ago, so the first pass after a long stop is judged by its own start, a long backup does not turn the container unhealthy and a stuck pass does. It also fails when the `jobs` heartbeat file is older than three beat periods (45 seconds), so a loop that stopped beating shows even while the record looks fine; a missing heartbeat file (first start) and no record file count as healthy. The first check runs after the start period, so `up --wait` takes about a minute longer.
* The Deletion history page shows "Last pass: <time>, ok" or "failed", or "No pass has finished yet", and nothing when there is no record file.

Why files and not rows: a restore replaces the database, so a row would be overwritten by the restore itself, and writing a row from `app` on every request would put a write on the single SQLite writer for the sake of a health signal. A file beside the database is on the volume that the restore already refuses to touch while services run, needs no transaction and survives the swap. A held lock would need a process that holds it for good, and the Docker API is not reachable from the containers and would add a dependency.

### The marker of an interrupted restore

`restore` writes `.restoring` into `pre-restore-<time>` after the stash is complete and before anything live is replaced, naming the backup it restores, and flushes it to disk. It removes the marker when the installation succeeded and when the previous data were put back after a failure. When putting back fails, or the process dies, the marker stays.

* A new restore refuses while any `pre-restore-*` directory holds a marker, names every such directory and points to the Restore section of [deployment.md](../../deployment.md#restore).
* `prune` never deletes a marked directory, whatever its age. This is the only thing in the backups volume that blocks without an age.
* A marker can also remain beside a good restore: the process died between the installation and the removal of the marker, or the removal failed (the restore then prints a warning). So the recovery text does not claim that a marker means damaged data: when the last restore printed "Restored" or warned that the marker could not be removed, the operator only removes the marker; otherwise (killed, failed) the operator puts the named directory back and then removes its marker. The refusal message says the same. The command prints "Restored" only after `restore()` returned, so a kill never belongs to the first branch.
* The put-back can succeed while removing its marker fails: the marker stays with no warning, and the next restore refuses. Following the "otherwise" branch is then harmless, because the data in the volumes already are the previous ones.
* Between `_stash` and `_mark` there is no marker and the live data are untouched: the stash is complete and harmless, and a crash there blocks nothing.
* The marker is written only after the stash is complete, so a crash during the stash leaves no marker and no refusal, only an incomplete `pre-restore` directory that `prune` removes by age like any other and that no restore ever puts back.

There is no `--force`: a marker is cleared by the documented recovery, not by a switch.

### The address key

`Participant.email_key` holds the address stripped and casefolded, as `name_key` holds the name. One function (`participants.email_key_of`) gives it, `claim_name` sets it where the address is stored, and migration `0020` fills it for existing rows in batches of 500 (the reverse removes it). The column is `max_length=762` (3 times the 254 of an address), because casefolding can make one character three. `search_email` filters on it in one indexed query and returns what it returned. The key is personal data like the address and goes with the row. `erase` clears the board cache of every run it touched after the commit, so a public scoreboard never shows an erased nickname.

Why a key and not a fingerprint: the key mirrors `name_key`, needs no secret, and a fingerprint of the address would stop matching when `KVZ_SECRET_KEY` is rotated. The stored fingerprint of an erasure ([ADR-0056](0056-retention-job-summary-held-runs.md)) stays what it is, a proof that an address was erased, and stays an HMAC because it outlives the row.

### The record of a purge

The summary that a purge writes first now also holds the trigger, the admin and a mark that a late export removal is still due, so a purge resumed by a pass keeps its trigger, an erasure that follows a stopped purge subtracts its rows from the summary instead of counting them twice, and a removal that did not work is retried by later passes for 24 hours. The warning that no exporter is installed is logged once per pass, and the stop flag is checked before each run. `RetentionProvider.record` rejects a trigger that is not one of the three.

After the stop flag is set `jobs` starts no backup and records the pass `stopped` (TD-072, resolved).

### Smaller changes

* The route `result_photo` takes the last part as a string and the view answers 204 for anything that is not a known id, so no 404 logs the path and the token in it. `/v/<token>/photo` without a slash is redirected by `APPEND_SLASH`.
* `play.with_files` appends to a list the caller owns, and `submit` deletes every file in it on any exception. `media_local` removes its final file when the row cannot be saved and its temporary file when writing fails.
* `prune` returns what it removed and what stayed. `manage.py backup` prints the backup, then writes the count that stayed to stderr and exits non-zero. The log of `jobs` names the count.
* `deploy/load.sh` retries the restore of its drill for up to 90 seconds, and only while the refusal is the one about a live heartbeat.

## Consequences

* Good: an idle running `app` or `jobs` is seen by a restore, and a crash cannot block it for more than a minute.
* Good: a stuck pass turns the container unhealthy and a finished one is on the Deletion history page.
* Good: an interrupted restore cannot be repeated on top of its half state by mistake, and `prune` cannot delete the data it replaced.
* Good: the erasure search is one query, and the board cache is cleared.
* Bad: a stopped service that left its heartbeat (a kill) makes a restore wait up to 60 seconds, and a clean stop of `app` may also leave a young file when `atexit` does not run.
* Bad: a marker that remains beside a good restore blocks the next one until it is removed by hand.
* Bad: a `jobs` that works through one pass for more than an hour is reported unhealthy.
* Bad: a failed `prune` shows as a warning in the log and as the exit code of `manage.py backup`, not on a page.
* Bad: one more column of personal data, and a migration that touches every participant row once.

### Confirmation

`tests/domain/test_heartbeat.py`, `tests/domain/test_jobs_heartbeat.py`, `tests/api/test_heartbeat_middleware.py`, `tests/test_deploy_healthcheck.py` and the history page cases of `tests/api/test_admin_retention.py` ([AC-144](../acceptance-criteria.md)); `tests/domain/test_restore.py`, `tests/domain/test_backup.py` and `tests/api/test_heartbeat_middleware.py` ([AC-143](../acceptance-criteria.md)); `tests/domain/test_backup.py` and `tests/domain/test_jobs_backup.py` ([AC-145](../acceptance-criteria.md)); `tests/domain/test_retention_erasure.py`, `tests/domain/test_identity.py` and `tests/domain/test_migration_0020.py` ([AC-146](../acceptance-criteria.md)); `tests/api/test_result_link.py`, `tests/api/test_image_answer.py` and `tests/providers/test_media_participant.py` ([AC-147](../acceptance-criteria.md)). `make load` waits for the heartbeats in its restore drill ([AC-139](../acceptance-criteria.md)).

## More Information

Refines [ADR-0059](0059-backup-and-restore.md) (the restore checks and the marker, `prune`) and [ADR-0056](0056-retention-job-summary-held-runs.md) (the pass record, the summary and the erasure search). Procedure: [deployment.md](../../deployment.md#restore).

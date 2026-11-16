---
status: accepted
date: 2026-11-09
---

# ADR-0056: Hourly retention in a `jobs` service, a summary in place of deleted rows, held runs and an e-mail fingerprint

## Context and Problem Statement

`FR-34` asks that a run's personal data go when its period ends and that an admin can delete selectively. Since C3 a run records its period ([ADR-0050](0050-data-profile-and-local-resume.md)), and nothing acted on it. Open were what runs the deletion, what a run still shows afterwards, what happens to runs already past their period when deletion first arrives, how an organiser can later show that an address was erased without keeping it, and where the code lives when providers may not import the domain.

## Decision Drivers

* Deleting is irreversible; a bug in "due", or a first pass after an upgrade, must not take data nobody chose to delete
* One SQLite writer: a live quiz must not wait behind a long deletion
* Statistics and the comparison of runs should stay true after the data go
* No personal value in `audit_event`, `retention_job`, a log or an event payload
* No cron daemon in the image and no new dependency
* `Attempt.participant`, `Attempt.run` and `Attempt.replaced_by` are `PROTECT`, and providers may not import `app/domain`

## Considered Options

* Scheduling: a `jobs` service looping in Python; a cron daemon in the image; only the host's cron; a thread in the app process
* A deleted run: keep a stored summary; delete and show nothing; anonymise the rows in place
* Runs already past their period: hold them for a confirmation; delete them on the first pass
* Proving an erasure: an HMAC of the address; the address itself; nothing

## Decision Outcome

Chosen: a `jobs` service, a stored summary with the profile rewritten to `none`, held runs, and an HMAC of the address, because together they make deletion automatic, keep what is worth keeping and never surprise an organiser with an irreversible first pass.

Rules:

* **Split.** `app/domain/retention.py` decides what is due and deletes, because the rows are the domain's. Provider `retention.local` (`app/providers/retention/`, port `retention`) only keeps the trail in `retention_job`: `record`, `history`, `for_run`, `erased`. Export files go through `ResultsExporterProvider.delete_for_runs`, photos through `MediaStorageProvider`.
* **Job.** The compose service `jobs` shares the app's image and volumes and runs `manage.py jobs`, which makes one pass at start and then every hour (`INTERVAL_SECONDS`) until SIGTERM. `manage.py retention` makes one pass by hand or from a host's cron. Each pass first settles runs past their deadline, so a run nobody visited has its true `closed_at`. The service's healthcheck is `["CMD","true"]`: the image's own check calls port 8000, and `compose up --wait` refuses a running service with no check. A crash restarts the container; a stuck loop would not show.
* **Due.** `closed_at + period <= now`, the period is not permanent, the run is normal, not held, and has no deletion recorded. A run that never closed has no clock. One run failing is logged by id and does not stop the others.
* **Stages, not one transaction.** `purge_run` is one path for expiry and "delete now". It stores the summary first, deletes attempts in batches of 200 in short transactions (untying `replaced_by` first), removes those photos after each commit, then in a last transaction deletes hidden values, entitlements and participants and marks the run. The stored summary holds what was counted, so a purge that stopped resumes with the same record, and the next pass also finishes a run with a summary and no `data_deleted_at`, even a permanent or held one. Only the last transaction writes `retention_job`, `audit_event` and `retention.executed`, so a run has one record however often it resumed.
* **Deleted run.** The row stays, rewritten to profile `none` with `stateless_submitted` set to the submitted count, moved to `ARCHIVED`, with `data_deleted_at` and its `retention_summary_json`. `run_stats` reads the summary instead of recomputing. It holds participants, started, submitted, unsent, score summary, per-revision summaries, per-question statistics only where the profile kept every answer, and the deleted row counts. The run can be restored from the archive without its data, and its period can no longer change. Public scoreboard, walkthrough and private links show the friendly "not available" state.
* **Exports.** Exports naming the run, or all runs of its quiz, go before the run counts as deleted and once more after, for a job created meanwhile. A queued or running job ends as failed with `run_data_deleted`, and its later write is refused. A failure to remove files stops the purge, and the next pass retries.
* **Held runs.** The migration sets `retention_held_at` on every normal run that is past its period, or past its deadline and unsettled and past its period counted from that deadline. The pass does not delete a held run. "Deletion history" lists them, and one confirmation releases the whole list for the next pass. Extending a held run's period past now clears its hold. Without a confirmation a held run stays for ever. A period shortened so that a run becomes due at once needs a confirmation in the form.
* **Sweep.** Each pass deletes files of `MediaAsset` rows with `private=True` older than one hour that no `AttemptAnswer.asset_id` refers to, so an admin's image or a photo being submitted is never touched.
* **Erasure.** A search across runs, test runs too, by normalised e-mail or by `name_key`; the admin ticks the rows. Those participants go with their attempts, answers, photos and entitlements in one transaction per run, and draw entries keep their pseudonym. The rest of the run stays, in any state. An attempt with no participant row cannot be found.
* **Fingerprint.** An erasure by e-mail stores in `retention_job.fingerprint` an HMAC-SHA256 of the normalised address, keyed from the server secret with the purpose label `kvz-erasure`. Retyping the address answers whether and when it was erased, and by whom. An erasure by nickname stores counts only. The address is never stored, and there is no free-text reason. Rotating `KVZ_SECRET_KEY` makes earlier fingerprints unverifiable, while the rest of the row stays.
* **Trail.** Every deletion writes one `retention_job` row and one `audit_event` with who, when, which run and how many rows of each kind. "Deletion history" (`/admin/retention`) lists them newest first, 200 a page, and is kept for ever because it holds no personal data.

### Consequences

* Good, because personal data go on their own and the organiser can still read a past run's numbers
* Good, because nothing past its period when D3 arrives is deleted without a person confirming it
* Good, because a live quiz waits at most for one short batch
* Good, because an erasure can be shown later without keeping the address
* Bad, because a crash can leave a run half deleted until the next pass; its summary is already in place and only the pass finishes it
* Bad, because one more container runs for one pass an hour, and its healthcheck did not detect a stuck loop until [ADR-0061](0061-heartbeat-and-restore-marker.md) made it read the record of the last pass
* Bad, because a summary of a run with one or two attempts reveals that person's score to an admin; it holds no identity
* Bad, because a downloaded export and a backup are outside this mechanism; backup retention is in [ADR-0059](0059-backup-and-restore.md)

## Links

Refines [ADR-0012](0012-configurable-retention-profiles-and-stateless-mode.md) and [ADR-0050](0050-data-profile-and-local-resume.md). Also refines [ADR-0046](0046-stored-answers-and-who-sees-them.md), [ADR-0049](0049-participants-and-access-code.md) and [ADR-0051](0051-scoreboard-participants-and-official-attempt.md), whose statements that deletion comes later held until D3. Keeps the pseudonyms of [ADR-0053](0053-rewards-tiers-alternates-and-draw-history.md). Takes over the export job of [ADR-0055](0055-results-export-background-job-and-csv-dialect.md) for deleted runs. FR-34, [AC-14](../acceptance-criteria.md), AC-110 to AC-119; [../../privacy.md](../../privacy.md), [../providers/retention.md](../providers/retention.md).

Refined by [ADR-0061](0061-heartbeat-and-restore-marker.md): the record of the last pass and the healthcheck that reads it, the trigger and the late export mark in the summary, and the erasure search by `email_key`.

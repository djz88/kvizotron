# D5 follow-up 2: operations are visible, restore is safe, small leaks closed

Closes TD-068, TD-085, TD-082, TD-089 (package C, jobs and backup), TD-021, TD-076, TD-015 (package D) and, as related items, TD-072, TD-074, TD-075. TD-086 is investigated and either closed or reworded. All before the tag `v1.0.0`.

## Why

D5 added a daily backup, a restore command and a `jobs` service, and the triage after it [user: "C-D, with the related TDs"] left these gaps:

- **C, nobody can see that the operations are healthy or that a restore is safe.** The `jobs` healthcheck is `true`, so a stuck loop is invisible (TD-068). `restore` cannot tell an idle running `app` or `jobs` from a stopped one and may lose submissions made between its stash and its placement (TD-089). A restore killed halfway leaves nothing that says so, and a second restore stashes the half state as the newest `pre-restore` (TD-082). `prune` logs a directory it cannot delete and `manage.py backup` still exits 0 (TD-085).
- **D, three small leaks.** A hand-crafted `/v/<token>/photo/<not a uuid>` is logged with the token (TD-021). Photos already written stay on the volume when a later photo of the same submission fails (TD-015). The erasure search loads every participant that has an address and compares in Python, and an erased nickname can stay on a public scoreboard for 5 seconds (TD-076).
- **Related**, because the same code is touched: the record of a purge is slightly wrong (TD-072, `retention.py`, `jobs.py`), and the tests and contract suites of retention have known gaps (TD-074, TD-075) around the code that TD-076 changes.

## Goals

1. **The `jobs` loop is visible [call].** `jobs` records when a pass started and finished and how it ended. The Deletion history page shows "last pass" (time and outcome). The `jobs` healthcheck fails when no pass has finished for two intervals, or when the first pass has not finished one interval after the start, so a stuck pass turns the container unhealthy.
2. **Restore refuses beside a live `app` or `jobs` [call].** Each writes a small heartbeat file in the directory of the database file while it runs; `restore` refuses while either is younger than the stale limit, and says which one and how long to wait. This closes TD-089.
3. **An interrupted restore is marked [call].** After the stash is complete and before anything live is replaced, `restore` writes a marker in the `pre-restore-<time>` directory and removes it when the restore ends, successfully or after it put the previous data back. A new `restore` refuses while any marker exists and names the directory to put back. `prune` never deletes a `pre-restore` directory that holds a marker.
4. **A backup that leaves old backups behind is not a success [call].** `prune` returns what it removed and what stayed; `manage.py backup` prints the backup, then a warning with the number that stayed and exits non-zero; the `jobs` log line names how many stayed.
5. **`/v/<token>/photo/<anything>` never logs the token [call].** The last part is taken as a string; anything that is not a known id answers 204, as an unknown id does now.
6. **No orphan photo files [call].** A failure anywhere while storing the photos of one submission removes the files already written for it, and `_saved` removes its file when its row cannot be saved.
7. **The erasure search is one query, and the board cache is cleared [call].** A new indexed column `Participant.email_key` holds the address stripped and casefolded (as `name_key` does for the name), is set wherever an address is stored, and is filled for existing rows by the migration. `search_email` filters on it. `erase` clears the board cache of the runs it touched.
8. **The record of a purge is accurate [call]:** a manual purge resumed by a pass keeps its trigger; a stopped purge followed by an erasure does not count rows twice; the "no exporter" warning is logged once per pass; a late export removal is retried; the stop flag is checked between runs inside a pass (TD-072 as written).
9. **The gaps in the tests are closed [docs: TD-074, TD-075]:** one test for each case TD-075 lists; the new retention, media and exporter methods are in the shared contract suites; `record` validates `trigger`; the retention suite compares with a set.
10. **TD-086 is measured, not guessed [call]:** find out whether a request from 127.0.0.2 reaches the application as a different address than 127.0.0.1 in the `kvizotron-load` stack. If it does, the probe uses both and its "not told apart" line goes. If it does not, the TD text is rewritten with the measurement. The photo-with-reveal half stays open: the application forbids the combination.
11. Every closed TD moves to the archive with `make tech-debt-resolve`.

## Non-goals

- A shared limit store, an external monitor, alerting, a status endpoint that shows `jobs` to the public. The page for admins and the container health are enough [call].
- A way to override the restore refusal (`--force`). A stuck marker is cleared by the documented recovery, not by a switch [call].
- Any change to what a backup contains or to the restore procedure itself beyond the checks above.
- A new setting. The heartbeat directory is the directory of the configured database file; the limits are constants [call].
- Allowing a photo question with reveal after each question (TD-086, second half), and the packages not named here: TD-047, TD-008, TD-091, TD-092.
- A JavaScript test harness (TD-039).

## Anti-goals

- A restore that refuses forever because a heartbeat file was left by a crash: a heartbeat counts only while young, and a marker is the only thing that blocks without an age.
- A restore that refuses falsely after a crash during the stash copy (the marker is written only after the stash is complete), or a marker that sends the operator to an incomplete directory.
- Deleting the only copy of the good data: `prune` keeps a marked `pre-restore` directory regardless of age.
- A healthcheck that restarts or marks unhealthy a `jobs` that is working through a long backup: the limit counts from the last finished pass, with two intervals of room.
- An `app` request that gets slower or fails because of the heartbeat: a failed write is swallowed and the write is rate-limited in the process.
- Personal data in logs: the new log lines carry counts and exception types only; the address in `email_key` is personal data and is erased like the address.
- Changing what the participant sees, what is scored or what is exported.

## Behaviour

### 1. Heartbeat, pass record and healthcheck

- A new module `app/domain/heartbeat.py` with small functions to write, read the age of, and clear a named heartbeat file, and to write and read the pass record. Files live beside the database file (`/data/db` in Compose); with an in-memory or missing database path every function does nothing [call]. The module is stdlib-only for the reading side, so a healthcheck can call it without Django's database.
- `jobs` writes its heartbeat from a daemon thread every 15 seconds while the process runs and removes the file on a clean stop (SIGTERM). The pass record is written when a pass starts (started time, no finish) and when it ends (finished time, outcome `ok` or `failed`; `failed` when the retention pass or the backup raised). A pass in progress keeps the previous finish until it ends [call].
- `app` writes its heartbeat from `RunClockMiddleware`'s neighbour, a small middleware that touches the file at most once per 10 seconds per process, on every request including `/healthz` (the image's healthcheck calls it every 10 seconds, so an idle `app` stays recent). A failed write is swallowed. It removes the file on a clean exit where that is cheap (`atexit`); otherwise it simply goes stale [call].
- Stale limit for both heartbeats: 60 seconds [call]. It is larger than the 15 and 10 second write intervals and the 10 second healthcheck.
- `restore` calls a check in `_require_unused`: if the `app` or the `jobs` heartbeat is younger than the limit, it raises `BackupError` with a fixed message naming the service and the seconds until it counts as stopped. The existing open-connection check stays.
- The `jobs` healthcheck in `deploy/compose.yaml` runs a command that reads the pass record and exits non-zero when the last finish is older than 7200 seconds, or when there is no finish yet and the start is older than 3600 seconds [call]. It uses no network and no database. The comment in the compose file that says "a running container is healthy" is replaced.
- The Deletion history page (admin, cs and en) shows "Last pass": the finish time in the configured time zone and the outcome, or "no pass finished yet". It reads the record file; it shows nothing alarming when `jobs` runs in another setup without the file [call].
- `deploy/load.sh`'s restore drill stops `app` and `jobs` before it restores; it must still pass, so the drill waits until the heartbeats are gone or old, and a clean stop removes them [call].

### 2. Marker of a restore

- In `restore`: after `_stash` has copied and synced the previous data and before `_install`, write `.restoring` in the stash directory (it names the backup being restored) and sync it. Remove it when `_install` succeeds, and when `_put_back` succeeds. When `_put_back` fails the marker stays and the message already names the directory [call].
- At the start of `restore`, after taking the lock, refuse if any `pre-restore-*/.restoring` exists: fixed message with the directory name and a pointer to the recovery in `docs/deployment.md`. The recovery procedure there gets a last step that removes the marker once the data are put back, and the text about "which pre-restore is the good one" is replaced by "the one the refusal names".
- `prune` skips a `pre-restore` directory that holds the marker, whatever its age.

### 3. `prune` and the `backup` command

- `prune(now, days)` returns an object with the removed directories and the ones that stayed (a small named tuple or dataclass; callers updated) [call].
- `manage.py backup` prints "Backup made: …" as now, then, when something stayed, a line to stderr with the count and exits non-zero (`CommandError` after the printed backup). `jobs` logs the count that stayed with the exception type of the first failure only.

### 4. `result_photo`

- In `app/urls.py` the route takes `<str:answer_id>`; the view validates it as a UUID and answers `_private(HttpResponse(status=204))` for anything else, exactly like an unknown id. No 404 for this route, so Django has no path to log [docs: TD-021].

### 5. Photo files

- `with_files` in `play.py` appends to a list the caller owns, and the caller removes every file in it on any exception, not only `ImageRefused`. `_saved` in `media_local` removes its file when the row cannot be saved. Removal failures are swallowed, with the exception type logged [docs: TD-015].

### 6. `email_key`

- `Participant.email_key`: `CharField(max_length=254, null=True, blank=True, db_index=True)`. One function gives its value (strip and casefold of the address, `None` for none), used wherever `email` is set; `search_email` filters on it and returns what it returns now. The migration adds the column and fills it for existing rows in batches; a reverse migration drops it. `retention` clears `email_key` wherever it clears `email` [call: the TD said "fingerprint"; a casefolded key mirrors `name_key`, needs no server secret, and an old fingerprint would break when the secret changes].
- `erase` clears the board cache for each run it touched, after the commit. A public scoreboard request after an erasure never shows the erased nickname.
- `docs/_architecture/data-model.md` and `docs/privacy.md` say that the column exists and that it is personal data with the address.

### 7. Purge record, tests, contracts, TD-086

- As in goals 8, 9 and 10; the builder reads TD-072, TD-074 and TD-075 for the exact items. TD-086 is a short investigation first (a `docker` run on the `kvizotron-load` stack or its project) and a code or documentation change after it.

## Constraints

- `app/domain/models.py` and its migration are LARGE; `deploy/compose.yaml` is LARGE; `app/domain/attempts.py` is not touched; `app/api/play.py` is at least MEDIUM. The work as a whole is LARGE [docs: profile].
- Single gunicorn process with threads: the heartbeat state in the process is a rate-limit on writes only.
- A new ADR (0061) refines ADR-0059 (restore checks and marker) and ADR-0056 (the pass record) and gets a "Refined by" line there. `docs/deployment.md`, `docs/privacy.md`, `docs/_architecture/security.md` (the log note), `data-model.md`, `modules/api-ui.md` (the page), `modules/domain.md`, `app/domain/CLAUDE.md`, root `CLAUDE.md` and `flows.md` follow.
- Acceptance criteria from the next free number; a test must name each, or `tests/test_docs.py` fails.
- Texts: admin cs/en only for the new page lines; "run", never "round". `make messages` at the end, and commit only the catalogs that changed.
- `tests/test_configuration_docs.py` must stay green: no new variable.
- Do not touch the data or global settings of the user's `kvizotron-browser` stack; use a new quiz with prefix `d7`. The user's `deploy/.env.example` and logo files are not touched.

## Risks

- **A heartbeat left by a crash blocks restore for up to 60 seconds.** Documented; the refusal says how long to wait.
- **A marker is the only block without an age.** If an operator deletes the half state by hand, the marker still sits in the stash directory and blocks restore until the recovery's last step (or an `rm`) removes it. The refusal names the file and the directory.
- **The healthcheck changes what `up --wait` does**: a `jobs` that fails its first pass for more than an hour turns unhealthy. That is the point; the smoke test must show the healthy case.
- **The migration touches every participant row.** Batches keep the lock short; on 50 participants per run it takes a moment.
- **No JavaScript in this work**, so the walkthrough only checks the new page lines.

## Left to the builder

Names of functions and constants, the exact file names of the heartbeat and pass record, the format of the pass record (text or JSON), whether `app` removes its heartbeat at exit, the batch size of the migration, the wording of the new messages, how many tests each behaviour needs, and how the healthcheck command is invoked (a `manage.py` subcommand or a stdlib script) as long as it needs no database.

## Verification

- Failing test first for each behaviour: restore refuses beside a young `app` heartbeat and a young `jobs` heartbeat and accepts an old or missing one; an interrupted restore (simulated failure after the marker) leaves the marker and the next restore refuses naming the directory; a successful restore and a failed one with a good put-back remove it; `prune` keeps a marked directory of any age; `prune` returns what stayed and `backup` exits non-zero; the pass record after a pass that succeeded, failed and is running; the healthcheck exits 0 and 1 at the limits; the history page shows the last pass; `result_photo` with a non-uuid answers 204 and logs nothing with the token; a failed second photo leaves no file, `_saved` removes its file on a failed row; `search_email` runs one query for many participants and ignores case; erasure clears the board cache; the migration fills `email_key`.
- `make quality`; `make smoke` (`SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543` while `kvizotron-browser` runs); `make load` for the restore drill and the TD-086 measurement.
- Browser walkthrough with a new quiz `d7-…`: the Deletion history page with "Last pass", before and after a pass.
- A fresh reviewer of the whole branch, on the most capable model, with extra attention to the restore order (stash, marker, install, remove marker) and to what `prune` may delete.
- `make tech-debt-check` after the closed TDs moved to the archive.

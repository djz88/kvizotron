# D5 Hardening & release: design

Tags: **[user]** the user decided, **[docs]** already in `docs/_architecture`, **[call]** my choice, open to correction.

## Why

D5 is the last milestone before v1.0 (`roadmap.md`: security hardening, rate limits, configuration docs, load test with 50 participants, backup and restore, acceptance tests). Release condition: every AC with Stage D and AC-01 to AC-18 green. Three things are missing today:

- Only the failed-access-code limit exists (`app/api/code_limit.py`). Login, submission and start have none, although ADR-0030 sets values and ADR-0044/0047 and `security.md` defer upload and link limits to D5.
- There is no backup of the database or of the media. `docs/deployment.md` and `docs/privacy.md` already require SQLite's backup mechanism, 30 days retention and a verified restore.
- AC-15 (50 concurrent participants, photo submissions, restore verified) has no test, 14 of AC-01 to AC-18 are in `AC_NOT_NAMED_BY_A_TEST`, and the configuration is described only in pieces.

## Goals

1. **Limits [user: ADR-0030 plus start]**: login, wrong access code, submission and attempt start are limited per client address, in process memory, thread-safe, values configurable. 50 people behind one address are never blocked at default values.
2. **Hardening [call]**: HSTS, an audit of the public routes and of response headers, and a documented list of what remains unlimited and why.
3. **Backup and restore [user]**: a daily backup of database and media into a dedicated `backups` volume, made by the existing `jobs` service; 30 days retention (configurable); a manual restore command with verification.
4. **Load test [user]**: a script against the Docker stack from one address with 50 clients including photo submissions, plus a small thread-based pytest in `make test`.
5. **Acceptance and docs [call]**: shrink `AC_NOT_NAMED_BY_A_TEST`, one configuration reference, release checks, version 1.0.0 once everything is green.

## Non-goals

- Technical debt triage and the blocking list: **[user]** "later, after this milestone". D5 touches TD-029 (closed by the start limit), TD-056 (measured by the load test) and TD-068 (not touched).
- GitHub CI (TD-008), a remote, a push or a tag without consent.
- A backup UI in the administration, off-site copies, encryption of backups, point-in-time recovery. The operator copies the `backups` volume off the machine.
- Limits in Caddy, a shared limit store, support for more than one application process [docs: ADR-0030].
- Limits on admin pages other than login (already behind login).
- New question types, settings scopes or plugins.

## Anti-goals

- A limit that stops 50 participants on one address from starting or submitting. Failing this fails D5 even if all tests pass.
- A backup made by copying the live SQLite file, or one never restored in a test.
- A restore that silently overwrites live data, or one that leaves files owned by root (`migrate` then fails with `unable to open database file`).
- Backups that keep deleted personal data longer than the stated retention.
- Personal data, answers, access codes or the secret key in logs of the new code.

## Behaviour

### 1. Limits

- One module replaces `code_limit.py`: named buckets over a sliding 60 s window, one lock, idle addresses swept. The existing client-address rule stays (Caddy writes the real address as the only `X-Forwarded-For` value) [docs: ADR-0030]. [call]
- Defaults and variables [call except the three first values, which are docs: ADR-0030]:

  | Bucket | Counts | Key | Default | Variable |
  |---|---|---|---|---|
  | login | failed logins | login name + address | 5/min | `KVZ_LOGIN_ATTEMPTS_PER_MINUTE` |
  | code | failed access codes | address | 10/min | `KVZ_CODE_ATTEMPTS_PER_MINUTE` (exists) |
  | submit | every submission POST | address | 120/min | `KVZ_SUBMITS_PER_MINUTE` |
  | start | every start POST | address | 300/min | `KVZ_STARTS_PER_MINUTE` |

- Login counts failures only, so a correct login is never refused for earlier typos by someone else; the key includes the address, so one address cannot lock an account for other addresses. A refused login still shows the login page with the same wrong-login message plus a "try again in a minute" message and status 429. [call]
- Submit and start count every request, because the point is to bound writes and rows. The start limit closes TD-029: a client without a cookie can create at most `KVZ_STARTS_PER_MINUTE` rows per minute. [user: start included; numbers are call]
- A refused request answers 429 with `Retry-After`; the public pages show a translated message (cs/en/uk), the admin login cs/en. Nothing counts a refused request again beyond the window. A restart resets the counters [docs].
- The builder audits every public POST and GET route (including test links, ADR-0044, and photo upload, ADR-0047) and reports which ones create rows or write to disk without one of these limits. Those that do get the bucket they belong to; the rest stay unlimited and are listed in `security.md`. [call]
- If, behind Docker, the application sees one gateway address for all clients (userland proxy, rootless Docker), the limits would be shared by everybody. The smoke or load run MUST show which address the application sees; if it is wrong, fix the deployment (compose or Caddy) or document the condition under which it holds. [call]

### 2. Hardening

- Caddy sends `Strict-Transport-Security: max-age=15552000`, without `includeSubDomains` and `preload`. [user: yes, six months, no preload] Browsers ignore it for an IP address and over an untrusted certificate (RFC 6797), so a LAN deployment by IP is unaffected; a LAN host name with a trusted local authority makes certificate exceptions impossible for six months. `deployment.md` says so. [call]
- Review of response headers (`X-Content-Type-Options`, `Referrer-Policy`, frame protection, `Cache-Control` on private pages) and cookie flags; missing ones are added where the effect is clear, and each one has a test. The builder lists what was checked and found fine. [call]
- Limits on body size stay as they are in `deploy/Caddyfile` [docs: ADR-0028, 0045, 0047].

### 3. Backup and restore

- A new volume `backups`, mounted only into `jobs`. [user] `restore` runs through the same service definition (`docker compose run --rm --no-deps jobs python manage.py restore …`) with `app` stopped. [call]
- `jobs` makes one backup per day [user: daily, not hourly]: at start if there is none for the current local date, then once per 24 h. The retention pass keeps its hourly interval. A backup is a directory `backups/YYYY-MM-DD/` with the database copy made by SQLite's online backup API (never a file copy [docs]), the media files and a manifest (file list, sizes, checksums, schema version, creation time). [call]
- Media: files already present in the previous backup are hard-linked, others copied, with a plain copy as fallback when linking fails. Each backup is therefore complete on its own, and deleting old ones frees space when the last one referencing a file goes. [call]
- A backup counts as made only after verification: `PRAGMA integrity_check` on the copy, the manifest checksums, and the migrations of the copy known to the installed code. A failed backup is removed, logged by exception type only and retried at the next pass; the previous backups are untouched. [call]
- Retention: `KVZ_BACKUP_RETENTION_DAYS`, default 30 [docs: `privacy.md`], applied after each backup attempt, including a failed one (backup retention is a privacy requirement; the newest valid backup is always kept). A value of at least 1 is required.
- `manage.py backup` makes one backup by hand; `manage.py restore <date|latest>` verifies the chosen backup, refuses if verification fails, keeps the current data in a sibling `pre-restore` directory instead of deleting it, replaces database and media, sets owner uid 1000, runs the migrations check and prints what was restored. It refuses to run while the database is locked by another process. [call]
- After a restore, runs past their retention period are deleted again by the next retention pass, and the privacy note says that an erasure request or deletion made after the backup date must be repeated by the operator. [call]
- `docs/privacy.md` loses "Backup retention is a matter for D5" and points to the mechanism. `docs/deployment.md` gets the backup and restore procedure, the restore drill and the off-machine copy recommendation. [docs]
- A failed backup shows only in the `jobs` log (`docker compose logs jobs`); no administration page [call], because TD-068 (visibility of the jobs loop) is outside D5.

### 4. Load test

- `tools/load_participants.py` and `make load`: starts a stack under a separate project name like `make smoke`, creates a quiz with a choice question and a photo question and a run, opens 50 clients **from one address**, each starts and then all submit at once with a photo of realistic size. [user: script against Docker stack] [call: details]
- Pass criteria: no response outside 2xx (no 5xx, no 429 at defaults), 50 submitted attempts and no more, each exactly once, a repeated submission with the same key creating nothing new, every photo stored once, no `database is locked` in the application log, slowest answer under the existing 5 s limit of `load_deadline.py`. After the run it makes a final backup, changes the live data, restores in the same stack and compares counts and checksums with those from before the change. [docs: AC-15]
- The script shows whether the application counts distinct client sources separately (a LAN source is refused while loopback traffic is not); it does not report the address itself because the application does not log client addresses. It also reports the number of database queries of one public page, so TD-056 gets a measured answer. If the measurement shows a problem at 50 participants, the builder reports it instead of fixing branding in D5. [call]
- A small pytest runs 50 threads against the Django test server or client on a file SQLite database with the same submit path and a tiny photo; it runs in `make test`, uses no network and no Docker. [user: quick pytest]

### 5. Acceptance and docs

- For each ID in `AC_NOT_NAMED_BY_A_TEST` the builder finds the test that proves it and names the ID in its docstring or name; if none exists, writes it. The set shrinks to the ones that only a person or the browser can check, each with a one-line reason. It never grows. AC-03 to AC-18 are all resolved or explicitly excused. [call]
- New AC from AC-129: limits (login, submit, start, shared address), HSTS and headers, backup made and verified, restore verified including ownership, retention of backups, load of 50 participants (AC-15 is the umbrella). [call]
- `docs/configuration.md` is the one list of every environment variable and where each global setting lives; `deployment.md` links to it instead of repeating the table. A test fails if a `KVZ_*` variable read in code or in `compose.yaml` is missing there. [call]
- Release checks in `deployment.md` (including backup, restore drill, load test, smoke) are completed and every item has a command. [docs]
- At close, `pyproject.toml` version becomes 1.0.0 only when the release condition holds; the Git tag is a separate step needing the user's consent. [call]

## Constraints

- A new module is not needed: limits are part of `app/api`, backup and restore are domain commands next to `jobs`. A provider for backups would be new architecture; decide in the plan with an ADR if the code does not fit [docs: ADR-0037, CLAUDE.md].
- `app/api/play.py` and `app/domain/attempts.py` are at least MEDIUM; `deploy/compose.yaml` and migrations (none expected) are always LARGE [docs: project profile]. D5 as a whole is LARGE.
- Single gunicorn process with threads; the counters must be safe for threads.
- Restore files are owned by uid 1000 [docs: `deployment.md`].
- New ADRs: one for limits beyond ADR-0030 (login keying, start bucket, 429 behaviour), one for backups. ADR-0030 gets a "Refined by" line.
- Texts: admin cs/en, public cs/en/uk, `make messages` after changes. Documentation in `docs/` in English. "Run", never "round", in UI texts.
- Do not touch the data or global settings of the user's `kvizotron-browser` stack; use a new quiz with prefix `d5`.

## Risks

- **Shared gateway address** in Docker makes per-address limits shared. Mitigation: measure in smoke and load; fix or document.
- **Restore resurrects deleted personal data** from a backup older than a deletion. Mitigation: 30 days default retention, retention pass after restore, operator note, no pretence that it is automatic.
- **Backup under write load**: the backup API and a busy writer both want the lock; with `timeout` 20 and `IMMEDIATE` transactions a backup could slow submissions. Mitigation: backup in small page steps; the load test runs a backup during the submissions in at least one run.
- **Disk growth**: 30 daily directories of media. Hard links keep it near one copy plus changes; the fallback copy does not. Documented.
- **Limits too tight for a shared address**: 300 starts/min is a call; the load test proves 50, not 300.
- **Scope**: this is one large milestone [user]. A review of the finished branch by one fresh reviewer, as in the milestone skill.

## Settled after the builder check (all **[call]**)

- Buckets and routes: `submit` is one POST per attempt (`/a/<id>/submit`), not per question, so 120/min covers 50 people finishing in the same minute with room to spare. `start` is `/r/<id>/start` only. The per-question `check` (reveal fragment, nothing stored), `attempt_time`, `resume` and `switch` stay unlimited unless the audit finds one that writes rows or files. The load test must use the heaviest mode (a question per page with reveal) so the request count per client is realistic.
- Docker address: the Docker default has to work out of the box. If the application sees a gateway address, D5 fixes it in `deploy/compose.yaml` or `Caddyfile` when the fix is small. If the fix is a design change (host networking, proxy protocol), stop and ask the user; documenting the condition is not enough for the release.
- Volumes: `backups` is mounted in `jobs` and in nothing else. `restore` runs as `docker compose run --rm --no-deps jobs …` with `app` and the running `jobs` stopped (the docs give `docker compose stop caddy app jobs`), and mounts `db` and `media` read-write like any `x-app` service. Caddy answers 502 while `app` is down; no maintenance page.
- Restore details: "locked" is detected by trying `BEGIN EXCLUSIVE` on the live database. It replaces the contents of the database and media directories, never the volume root. `pre-restore` lives in `backups`, so it is subject to the same retention as backups (it is pruned like a dated backup).
- Personal data in backups: `docs/privacy.md` already fixes backup retention (30 days, configurable) as independent of the per-run retention. No redaction or pruning of backups by erasure request.
- `make load` is not part of `make quality`, since CI does not exist (TD-008). It runs once at close and its output goes into the closing report; the pytest version with threads runs always.
- Existing `code_limit` tests keep their assertions. Only the imports and the module they call change, and `KVZ_CODE_ATTEMPTS_PER_MINUTE` keeps its name and meaning.

## Left to the builder

Names of modules, commands and make targets; the bucket structure; exact photo size in the load test; whether the backup lives in `app/domain` or a small provider (decide with an ADR); the wording of 429 messages and of the manifest format; which header additions are justified; how many acceptance tests need new code versus a name; whether `make load` needs a bigger smoke timeout.

## Verification

- Failing test first for each behaviour: limits per bucket, 429 with `Retry-After`, 50 addresses-behind-one not blocked at defaults, restart of counters, thread safety.
- Backup: made while the app writes, verified, failed one removed, retention deletes the 31st day, hard links, restore verified including owner and a corrupted backup refused.
- `make quality`, `make smoke` (with `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543` while `kvizotron-browser` runs), `make load` with output, browser walkthrough of the login 429 and the pages that changed, `kvizotron-check-applied`, a fresh reviewer for the whole branch.
- Acceptance: `tests/test_docs.py` passes with a smaller `AC_NOT_NAMED_BY_A_TEST`; every AC with Stage D and AC-01 to AC-18 listed green in the closing report.

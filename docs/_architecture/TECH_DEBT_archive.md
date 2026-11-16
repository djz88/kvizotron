# Technical Debt — Archive

Full details of resolved items from TECH_DEBT.md. Read only when investigating regressions.

## RESOLVED

### TD-072 SIGTERM waits for a backup that is due — ✅ RESOLVED (2026-11-16)
- Where: `app/domain/management/commands/jobs.py` (`_work`)
- Effect: after the stop flag is set the retention pass ends between runs, but `_work` still runs `backup.due`, `create` and `prune` and records the pass `ok`, so `docker compose stop` waits for a backup that was due until Compose kills the container. The rest of the old list (trigger kept in the summary, no double count after an erasure, one no-exporter warning, a retried late export removal, the stop flag between runs) is closed by [ADR-0061](adr/0061-heartbeat-and-restore-marker.md)
- Solution: check the stop flag before the backup, and record a pass that stopped early as neither `ok` nor `failed` (or as `stopped`)

### TD-026 MediaStorageProvider has no shared contract suite — ✅ RESOLVED (2026-11-11)
- Where: `tests/providers/test_media_local.py`, `tests/test_wiring.py:34`
- Effect: the project rule asks every module to pass a shared suite in `tests/contracts/`. `media_local` has only its own tests, so a second media provider would have nothing to prove itself against
- Solution: add `tests/contracts/media_storage.py` when a second provider is planned, and drop the exception

### TD-075 Gaps in the tests of deletion — ✅ RESOLVED (2026-11-10)
- Where: `tests/domain/test_retention*.py`, `tests/api/test_admin_retention.py`
- Effect: No test for the by_revision freeze with several revisions, a failure inside `_finish`, `delete_now` refused on a scheduled run, draw actions refused on a deleted run, or the ProtectedError path in `_finish`
- Solution: Add one test for each

### TD-074 Contract gaps for retention, media and exporter — ✅ RESOLVED (2026-11-10)
- Where: `tests/contracts/retention.py`, `app/contracts/`
- Effect: The new media and exporter methods are in no shared contract suite; `record` does not validate `trigger`; the retention suite compares with a list
- Solution: Add the methods to the shared suites, validate `trigger` in `record` and compare with a set

### TD-015 Photo files left behind when storing fails midway — ✅ RESOLVED (2026-11-10)
- Where: `app/api/play.py:337` (`with_files`), `app/providers/media_local/provider.py:236` (`_saved`)
- Effect: if a later photo of one submission fails with anything but `ImageRefused`, such as a full disk or a locked database, the photos already written stay on the volume with no row pointing to them. `_saved` also writes the file before its row, so a failed save leaves one file. Nobody sees them, but they take space
- Solution: let `with_files` append to a list the caller owns and remove it on any exception; remove the file in `_saved` when the row cannot be saved

### TD-076 Erasure by address loads every participant with an address; the board cache outlives an erasure — ✅ RESOLVED (2026-11-10)
- Where: `app/domain/retention.py` (`search_email`), `app/domain/results.py:215`
- Effect: `search_email` compares every participant that has an address in Python; an erased nickname can stay on a public scoreboard for up to 5 seconds
- Solution: Store the fingerprint of each address to query by it, and clear the board cache in `erase`

### TD-021 Hand-crafted result photo address logs its token — ✅ RESOLVED (2026-11-10)
- Where: `app/urls.py:24`, the `uuid` part of `result_photo`
- Effect: `/v/<token>/photo/<not a uuid>` answers 404, and Django logs that with the path, so a token can reach the log. Only a hand-crafted address does this; pages never link to one
- Solution: take the last part as a string, and answer 204 for anything that is not a known id

### TD-089 D5: restore cannot detect an idle running app or jobs — ✅ RESOLVED (2026-11-10)
- Where: `app/domain/backup.py` (`_require_unused`), [ADR-0059](adr/0059-backup-and-restore.md), `docs/deployment.md` (Restore)
- Effect: the refusal "database in use" sees only a connection that is open at that moment (a request or a pass in flight). A running but idle `app` or `jobs` closes its connections after every request or pass (`CONN_MAX_AGE` 0), so nothing shows and a restore beside them is accepted; submissions made between the stash and the placement can be lost. Stopping `caddy app jobs` first is the operator's job
- Solution: a heartbeat file that `app` and `jobs` write in `/data/db` while they run (touched on each request or pass, removed on a clean stop), and restore refuses while it is recent; needs a small decision on where `app` writes it and how stale it may be

### TD-082 D5: a restore that was interrupted leaves no marker — ✅ RESOLVED (2026-11-10)
- Where: `app/domain/backup.py:435` (`restore`), `app/domain/backup.py:515` (`_stash`)
- Effect: a restore killed halfway (power cut, `docker kill`) leaves a half-replaced database and media beside a `pre-restore-<time>` directory, with nothing that says it was interrupted. Running `restore` again stashes that half state as the newest `pre-restore`, so the operator has to know which one holds the good data (the older one). `docs/deployment.md` describes the manual recovery
- Solution: write a marker file in the stash before the replacement and remove it when the restore ends; refuse a new restore while a marker exists, and print which `pre-restore` directory to put back

### TD-085 D5: prune logs a failed deletion and the backup command still exits 0 — ✅ RESOLVED (2026-11-10)
- Where: `app/domain/backup.py:245` (`_remove`), `app/domain/management/commands/backup.py`
- Effect: `prune` logs a directory it cannot delete (by exception type) and carries on, so `manage.py backup` still prints the backup and exits 0 although old backups stay beyond their retention. Only the log shows it
- Solution: return the directories that stayed and let the command print a warning and exit non-zero, and make the `jobs` log line name how many stayed

### TD-068 The jobs service has no real healthcheck and no sign of the last pass — ✅ RESOLVED (2026-11-10)
- Where: `deploy/compose.yaml`, `app/domain/management/commands/jobs.py`
- Effect: The healthcheck of the jobs service always passes, and nothing shows when the last retention pass ran, so a stuck loop is invisible
- Solution: Write a heartbeat after each pass, check its age in the healthcheck and show "last pass" on the Deletion history page

### TD-041 Public scoreboard response has no Vary: Accept-Language, Cookie — ✅ RESOLVED (2026-11-10)
- Where: app/api/scoreboard.py, `_cache`.
- Effect: Without a cookie the answer is `public, max-age=5`, but its language can come from Accept-Language and its "you" mark from the cookie; a shared cache keyed on the URL could serve another language or drop the mark. The stack has no shared cache today.
- Solution: Add `Vary: Accept-Language, Cookie`, or answer `private` everywhere.

### TD-081 D5: no per-address ceiling across login names — ✅ RESOLVED (2026-11-10)
- Where: `app/api/admin_auth.py:52` (key `name|address`), [ADR-0058](adr/0058-rate-limit-buckets.md)
- Effect: one address may try 5 wrong passwords per minute for every name, so it can spray many names (and the same few common passwords) without being stopped. The per-name limit only protects each single account, and it is what lets one address not lock an account for others
- Solution: add a second `login` ceiling keyed by address alone, well above the per-name value, with its own variable, and decide in ADR-0058 how it counts a shared office address

### TD-090 D5: login limit checks and records in two steps, so parallel guesses can pass — ✅ RESOLVED (2026-11-10)
- Where: `app/api/admin_auth.py:53` (`rate_limit.allow`) and `app/api/admin_auth.py:63` (`rate_limit.record`), `app/api/rate_limit.py`
- Effect: the window is checked before `authenticate()` and a failure is stored only after it returns, so parallel wrong guesses for one name and address can all pass the check first. With gunicorn's 8 threads at most 7 guesses over the limit of 5 slip through per minute; once they are recorded the key is blocked for the rest of the window. A correct login is still never counted
- Solution: `rate_limit.try_acquire(bucket, key, now)` that checks and appends under one lock acquisition; the login view reserves a slot before `authenticate()` and releases it when the login succeeds; a test with parallel wrong logins must not exceed the limit

### TD-018 Number answer with a thousands separator is graded wrong without a message — ✅ RESOLVED (2026-11-10)
- Where: `app/plugins/questions/number/plugin.py:39` (`parse_number`)
- Effect: a comma is a decimal separator as the docs say, so `1,000` reads as 1 and is graded wrong, with only the hint under the field to warn about it
- Solution: ask to confirm or show a message for exactly three digits after a separator, in the page's script and without changing what the server accepts

### TD-051 C5: an IntegrityError from refresh is reported as a used submission key — ✅ RESOLVED (2026-11-10)
- Where: app/domain/attempts.py `_store`, the `except IntegrityError` around the submission transaction.
- Effect: A unique-constraint failure from `rewards.refresh` would be reported as `submission_key_used`. Unlikely under IMMEDIATE transactions, but it hides the cause.
- Solution: Narrow the handler to the submission key constraint, and add a query-count test for `refresh`.

### TD-084 D5: the 429 refusal uses the locale of the query and header, not the form's — ✅ RESOLVED (2026-11-10)
- Where: `app/api/i18n.py:62` (`_public_locale`), `app/api/play.py:164` (`_limited`), `app/api/jinja2/public/quiz.html:53`, `app/api/jinja2/public/_questions.html:5`
- Effect: the middleware reads only `?lang=` and `Accept-Language`, never the form body (it would defeat the body limits), so a 429 on `start` or `submit` is shown in the browser's language, not in the language the participant chose on the form (the `lang` field)
- Solution: add `?lang={{ locale }}` to the action and `hx-post` of the start and submit forms, as `revision_status` already does

### TD-083 D5: an automatic submission refused with 429 is not sent again — ✅ RESOLVED (2026-11-10)
- Where: `app/api/assets/countdown.js:138`, `app/api/play.py:164`
- Effect: an automatic submission at the deadline that is refused with 429 (the submit bucket is full for that address) is not sent again: the script repeats only after `htmx:sendError`. The refusal carries `Retry-After: 60`, so by the time it could be repeated the deadline has usually passed. Related to TD-022, which covers 5xx
- Solution: repeat on 429 after `Retry-After` while the server still accepts the attempt, and show the participant that the submission is waiting; decide together with TD-022
- Resolution (D5 follow-up): resolved only as far as the repeat exists. A 429 repeats after `Retry-After`, at most twice, with a waiting note. `Retry-After` is always 60 seconds, which is after the limit, and the server rejects any send after the limit, so the case that matters at the deadline is not recovered by waiting: it is [TD-091](TECH_DEBT.md)

### TD-022 Automatic submission is not repeated after a server error — ✅ RESOLVED (2026-11-10)
- Where: `app/api/assets/countdown.js:138`
- Effect: the page repeats it only after a network error. A 5xx or a connection that hangs leaves the page waiting, the time runs out, and the attempt is lost
- Solution: also repeat on `htmx:responseError` with status 500 or more and on `htmx:timeout`, and give the request a timeout
- Resolution (D5 follow-up): the automatic submission is sent when 5 seconds or less remain and repeated after a lost connection and a 5xx at 1, 1, 1.5, 3, 6 and 12 seconds, with the same submission key. Only the first three repeats fall inside the margin before the limit, so a failure that clears within about 3.5 seconds can be saved; a later repeat gets the server's explicit verdict (`attempt_expired`) instead of silence. There is no request timeout: a hung request is not cut and not repeated ([TD-092](TECH_DEBT.md))

### TD-029 C2: a start POST without a cookie creates a Participant row each time; limit with D5 — ✅ RESOLVED (2026-11-10)
- Where:
- Effect:
- Solution:

### TD-017 Closed quiz page fails when a question type's module is uninstalled — ✅ RESOLVED (2026-11-09)
- Where: `app/domain/walkthrough.py:74` (`_plugin`), called from `available` and `of_run`
- Effect: after a question type's module is uninstalled, the public page of an ended quiz answers 500 when its answers are not public, and the walkthrough answers 500 in any case
- Solution: catch `UnknownPort` as `_own_answers` in `app/api/public.py` does, and leave such a question out

### TD-067 Retention (D3) must delete export_job files of affected runs — ✅ RESOLVED (2026-11-09)
- Where: `app/providers/csv_io/results.py`, retention job of D3
- Effect: Export files of a run whose data are deleted by retention stay on the volume until the job expires (at most 24 hours).
- Solution: When D3 deletes a run's data, delete `export_job` rows and files whose choices name that run or its quiz with all runs.

### TD-010 Admin editor rough edges — ✅ RESOLVED (2026-11-06)
- Where: `app/api/admin_quizzes.py`, `app/domain/authoring.py`, `app/api/admin_forms.py`, `app/api/jinja2/`
- Effect: a double click on Save adds a question twice. Changing only "featured" reports unpublished changes and creates a draft. A slug race, or a double click on Create, answers 500 or a misleading "identifier in use". The percentage shows as `50.0 %`, and the admin sees the id `choice.single`.
- Solution in B2 with the full editor: per-form key or disabled button, draft only for snapshot fields, the `IntegrityError` pattern from `admin_users.py`, locale-aware numbers, a `label` on question types.

### TD-009 Request bodies are not limited at the proxy — ✅ RESOLVED (2026-11-06)
- Where: `deploy/Caddyfile`, `app/api/play.py`
- Effect: file parts of a multipart request do not count towards `DATA_UPLOAD_MAX_MEMORY_SIZE`, so an anonymous client can stream large uploads to temporary files. `multipart/form-data` with an invalid charset answers 500.
- Solution in D5: `request_body { max_size }` in Caddy, and start and submit accept only urlencoded forms.
- Resolved: Caddy `request_body { max_size 16MB }`; `RefuseMultipartMiddleware` answers 415 to every multipart POST, so also on the public login.

### TD-011 Escaping is tested per plugin, not in the shared contract — ✅ RESOLVED (2026-11-06)
- Where: `tests/contracts/question_type.py`, `tests/contracts/test_choice_single.py`
- Effect: `render_public` and `render_admin` output is marked safe, so a new question type that does not escape would pass the contract suite.
- Solution in B2, before the next types: move both escaping tests into `QuestionTypeContract`.
- Resolved: Tests moved into `QuestionTypeContract`; `HOSTILE` text in `render_public` and `render_admin`.

### TD-012 Small leftovers from the B1 review — ✅ RESOLVED (2026-11-06)
- Where: `app/api/admin_quizzes.py` (`_free_slug`, `_archived_message`, `quiz_restore`), `app/domain/authoring.py` (`discard_draft`, `publish`, `restore_quiz`), `app/domain/attempts.py` (`_switch`)
- Effect:
  - The suggested slug of a duplicate ends in the Czech `-kopie`, also for en and uk admins. It can be edited.
  - The `quiz.draft_discarded` audit row has no revision number, and the next draft reuses the discarded draft's number.
  - Restoring a quiz that is not archived changes nothing but writes a `quiz.restored` audit row.
  - `_archived_message` carries a pointless `# noqa: N802`.
  - `publish` reads the open round in two queries; a round opened or closed between them could get a decision that does not match. SQLite serialises writers, so the effect is tiny.
  - A switch on the current revision issues a new token and submission key, which keeps retries working, but no docstring says it is intended.
- Solution: a neutral suffix such as `-copy`, `revision_no` in the audit details, no audit row when `archived_at` is already empty, remove the `noqa`, read the round once, add the docstring.
- Resolved: All but the reused number of a discarded draft, which stays because avoiding it needs a new column; the audit row names the number.

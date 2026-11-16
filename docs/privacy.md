# Privacy & Data Retention

Applies to the Kvízotron v1.0 architecture. This is not a legal assessment of any specific
processing; the operator determines the legal basis for their deployment.

## Requirements

- `FR-32` Per run, admin configures collection and presentation of public name/nickname and e-mail
  (`DISABLED`, `OPTIONAL`, `REQUIRED` for e-mail). Data are requested at the end, before submission,
  or before the start, as the admin chooses; the end is the default. Validation happens on the server.
- `FR-33` Admin chooses a data-retention profile: aggregate score only; score + individual answers;
  detailed times and history. Settings respect functional dependencies. E-mail is stored only if it is
  actually required for a declared purpose.
- `FR-34` Retention per run: e.g. 30/90/365 days or permanent; periodic cleanup anonymises or deletes
  matching personal records per policy. Restarting a run does not bypass retention. Admin can delete
  data selectively. Backups must have their own limited retention so that deleted personal data are
  not restored without reason.
- `FR-35` The participant receives basic information about data processing and a link to the privacy
  policy. The policy must describe purpose, controller, retention period and contact; the legal basis
  is determined by the specific deployment. It must not be assumed that consent is required for all
  purposes.

## Functional dependencies of retention profiles

| Feature | Requires stored |
|---|---|
| Public scoreboard | attempt score + participant (nickname) |
| Draw / rewards | attempt score + participant (+ contact if winner must be reached) |
| Attempt limit across sessions | participant key hash + attempt |
| Per-question statistics | individual answers |
| Duration-based ranking | detailed times |
| Image answer type (FR-45) | individual answers + uploaded images |
| None of the above (stateless mode) | nothing — score only shown to participant (FR-31) |

Admin UI shows these dependencies and the retention setting **before** activating data storage.
The table is a summary; the profile below decides what is kept. The scoreboard, draws, statistics and
export that need more than a profile keeps refuse to run on it from C4, C5 and D2.

## Data profile and retention period

A run keeps what its data profile says ([ADR-0050](_architecture/adr/0050-data-profile-and-local-resume.md)). The profile replaces `store_answers`, is inherited global → quiz, copied onto the run when it is planned or opened, and fixed once the run opens.

| Profile | Kept after submission |
|---|---|
| `none` | Nothing per attempt; the run keeps a count of submitted attempts |
| `score` (default) | Score, submission time, and answers a person must grade, photos included |
| `answers` | As `score`, plus every answered question |
| `detailed` | As `answers`, plus the attempt's duration |

- Under `none` the participant sees a score and nothing remains: the attempt row is deleted at submission with the attempts it replaced, and no private result link exists. The form refuses `none` with repeating forbidden, a name or e-mail asked, visible answers or a photo question. A test run follows the live profile and does not count.
- The period (30, 90 or 180 days, 1 year, 3 years or permanent, 90 days by default) is counted from the run's close and stays editable on the run until its data are deleted. The public privacy page shows the global default, says a quiz may set another, and says the data are then deleted automatically.

## Deletion of a run's data

Implementation: [providers/retention.md](_architecture/providers/retention.md); decision: [ADR-0056](_architecture/adr/0056-retention-job-summary-held-runs.md).

- A job makes one pass per hour. When a run's close plus its period has passed, its data are deleted with no admin action. A permanent period, a run that never closed and a test run are left alone.
- Deleted: every attempt of the run in any status with its answers, hidden answer values and assigned questions; participants (names, e-mails, cookie hashes); reward entitlements; participant photos; export jobs and files that name the run or all runs of its quiz. A job in progress ends as failed, so no file can appear afterwards.
- Kept: the run, its revisions and reward rules; draws with the participant link cleared and the pseudonym left; the admins' audit events; an anonymous summary on the run (participants, started, submitted, unsent, average and percent, per revision, and per question only where the profile kept every answer). A summary of a run with one or two attempts reveals a score, not a person.
- Afterwards the run is archived and labelled as deleted. It can be restored from the archive, but the data do not come back, and its period no longer changes. The public scoreboard, walkthrough and private result links say the result is not available.
- Runs that were already past their period when deletion arrived, or past their deadline and unsettled, are **held**: nothing deletes them until an admin confirms the list on the Deletion history page, and they stay for ever without that. Extending a held run's period past now clears its hold. A period shortened so that a run is due at once needs a confirmation that says so.
- An admin can delete a run's data at any time after it ends ("Delete data now"), which does exactly what the period would do.
- An erasure request deletes chosen participants, found across all runs by e-mail or by nickname, with their attempts, answers, photos and entitlements, in a run in any state. Draw entries keep their pseudonym. Nicknames can be shared, so the admin ticks the rows meant. An attempt with no participant row cannot be found this way, as nothing ties it to a person.
- The reason an admin types for a draw action stays with the draw history after deletion, so it must not name people. An erasure clears the cache of the public scoreboard of each run it touched, so an erased nickname does not stay on it. If the results exporter module is absent, export files are not removed; they still end on the normal 24-hour tidy once it returns.
- Every deletion leaves one row in `retention_job` and one audit event with who, when, which run and how many rows of each kind, and no personal value. The history is kept for ever.
- An erasure by e-mail also stores a fingerprint: an HMAC-SHA256 of the normalised address, keyed from the server secret with a purpose label of its own. The address is never stored. Typing the address on the Deletion history page answers whether and when it was erased, and by whom. Rotating `KVZ_SECRET_KEY` makes earlier fingerprints unverifiable ([deployment.md](deployment.md#minimum-operational-elements)). An erasure by nickname stores counts only.
- To find an address in one query, the participant row also holds `email_key`: the address stripped and casefolded (up to 762 characters, because casefolding can triple an address). It is personal data like the address itself, is set where the address is stored and goes with the row on a deletion of a run's data and on an erasure ([ADR-0061](_architecture/adr/0061-heartbeat-and-restore-marker.md)). It is not the fingerprint, which stays after the row is gone.
- A file already downloaded is outside this mechanism. A backup is outside it too, with a retention of its own: see [Backups](#backups).

## Backups

Implementation and procedure: [ADR-0059](_architecture/adr/0059-backup-and-restore.md), [deployment.md](deployment.md#backup-and-restore).

- The `jobs` service makes one backup of the database and the media per day, into a volume only it mounts. A backup holds everything that was stored at that moment, personal data included, so it is bounded: backups older than `KVZ_BACKUP_RETENTION_DAYS` (default 30) are deleted after every backup attempt, also after a failed one. The newest backup that still verifies is always kept, however old, so that the installation is never left without one.
- Backups leave out the transient files under the media root: the results exports (`exports/`, which hold e-mails and every photo of a run) and the uploaded imports (`imports/`). They live for at most 24 hours on the server, and no backup keeps them.
- Exports and backups are outside the per-run retention period. Backups are bounded by the backup retention; a downloaded export file by the 24 hours it lies on the server, after which the organiser's own copy is the organiser's responsibility.
- A restore brings back what the backup held. The next hourly pass deletes runs past their period again, except runs that the backup still holds as held ([ADR-0056](_architecture/adr/0056-retention-job-summary-held-runs.md)), which an admin confirms on the Deletion history page. An erasure request, a "Delete data now" or any other deletion made after the backup date comes back with the backup, and the operator must repeat it; the Deletion history of the restored database does not know about it.
- The data that a restore replaces are kept in `pre-restore-<time>` in the backups volume and pruned like a backup, so they leave after the same number of days.
- A copy of the `backups` volume made outside the machine is the operator's own copy, and its retention is the operator's to keep within the same limit.

## Rules

- Images a quiz loads from their own server (`external_image_mode`, off by default) let that server
  see the participant's IP address. Copies kept by the installation do not. The public privacy page
  says so.
- Images uploaded by participants may show people and are treated as personal data: visible only to
  admins, EXIF removed, deleted with the answers under the run's retention.
- No marketing consent and no e-mail mailing module in v1.0.
- A participant's e-mail is never published and never sent to external analytics.
- An admin's account e-mail is optional. When set, it is shown publicly as the contact in the footer of every quiz that admin created and that sets no contact e-mail of its own, and so is a contact e-mail set in branding ([ADR-0054](_architecture/adr/0054-branding-owned-by-domain-and-theme.md)); the forms say so. A quiz created before audit history existed was assigned to the oldest admin by a migration, so that admin's e-mail may be the public contact of those quizzes until they set their own. Audit records of a change hold no address.
- Draw and audit logs minimise PII (audit details also hold the eligible count and the fingerprint of the eligible set, no personal data); on retention expiry or erasure request personal data are deleted
  or pseudonymised while non-personal draw metadata may stay (FR-39, [plugins/drawings.md](_architecture/plugins/drawings.md)).
- A draw record keeps, next to each participant link, a pseudonym: a salted HMAC-SHA256 of the
  participant id with the server secret. Draw audit records and `audit_event` hold only pseudonyms and
  ids of rules and draws, never a name, an e-mail or a reason typed by the admin about an entitlement
  ([ADR-0053](_architecture/adr/0053-rewards-tiers-alternates-and-draw-history.md)).
- Backups are kept for 30 days by default (configurable), see [Backups](#backups). Exports and backups **MUST** be verified not to bypass retention rules: deleting after retention is tested for the backups (`prune`) and for the export files (24 hours).
- A results export ([ADR-0055](_architecture/adr/0055-results-export-background-job-and-csv-dialect.md)) holds only what the run's data profile keeps: under `none` only the count of submitted attempts, photos only where the profile keeps them, never unsubmitted or test attempts, answer keys, tokens or the access-code hash. A draw lists winners and alternates by nickname and participant id, a pseudonym once the participant is deleted; e-mails appear only in the participants and entitlements files. Choosing a file with personal data (every file except question statistics) or photos needs a confirmation; photos come only in a ZIP with the answers file and count as personal data. The files lie on the media volume for 24 hours, are never served by the media route and are downloaded only by the admin who asked for them; after that they are deleted on the next use of the export page, and at once when the data of a run they name are deleted. The audit records `export.created` (quiz, run ids, files, photos, whether personal data were included) and `export.downloaded` (file name) with the admin, never a value from a file. A file once downloaded is outside the application's retention; deleting it is the organiser's job.
- Implementation: [providers/retention.md](_architecture/providers/retention.md);
  decision: [ADR-0012](_architecture/adr/0012-configurable-retention-profiles-and-stateless-mode.md);
  [ADR-0056](_architecture/adr/0056-retention-job-summary-held-runs.md);
  default period: [ADR-0029](_architecture/adr/0029-default-retention.md).

## Stored answers and photos

Answers are stored only as a quiz's data profile says ([ADR-0046](_architecture/adr/0046-stored-answers-and-who-sees-them.md)). By default only what a person grades is kept, photos included; the profiles `answers` and `detailed` keep each answered question (they replace `store_answers=all`).

- Who sees answers: `answers_visibility` chooses admins, the participant through a private link, or everyone on a walkthrough after the run ends, without naming anyone.
- Who sees a photo: `photo_visibility` ([ADR-0047](_architecture/adr/0047-image-answer-photo-visibility.md)). Public needs that level, approval of that photo, and a notice shown before upload.
- A photo is rebuilt from pixels, so EXIF and any other metadata are gone. It stays until an admin deletes it, its test link is deleted, or the run's data are deleted.
- The private link has no end date of its own; once the attempt is deleted with the run's data it says the result is not available. Anyone holding it can open it, so the result page asks to save it.
- While an attempt is unfinished and the quiz allows it (`local_resume`, on by default), the browser keeps its token, the entered answers, the step and an expiry in `localStorage`, per run: no photo, name or e-mail. The copy is deleted on submission or when the attempt ends, and is not kept past its expiry of 24 hours at most: the next page of this site that you open removes an expired copy. Another person on the same browser could see those answers meanwhile; the quiz page says so, and an admin can turn it off. The copy decides nothing: the server re-checks every answer and keeps the start and questions.
- The participant's browser keeps that link in `localStorage`, per quiz, on that device. Nothing about it is sent anywhere. Without a script only the link itself works.

## Participants, names and e-mails

How a run identifies people and what it keeps ([ADR-0049](_architecture/adr/0049-participants-and-access-code.md)):

- A run that forbids repeating, asks for a name or e-mail, or shows a public scoreboard sets the cookie `kvz_p_<run>` with a random key ([ADR-0051](_architecture/adr/0051-scoreboard-participants-and-official-attempt.md)). The database keeps only an HMAC of that key with the run id, so runs cannot be linked through it. Other runs set no cookie and store no participant.
- A run with an access code sets the cookie `kvz_c_<run>` after a correct code. It says only that this browser entered the current code, and holds neither the code nor any identity.
- E-mails are shown only in the logged-in administration, on the run's page. Nicknames are shown there too, and on the run's public scoreboard when the admin turns it on: during the run they can be replaced by anonymous labels, and a participant without a nickname is shown with an anonymous label or left out. The scoreboard never shows an e-mail or an internal id. They are not written to logs or audit records, and pages that show them back to the participant are not cached.
- A run with reward rules sets the cookie too, so one browser holds one set of entitlements. A winner's e-mail is shown only on the run's rewards and draw pages in the administration; the system sends no e-mail. Published draw winners appear on the run's public scoreboard page by nickname, or by the anonymous label when there is none. A participant's own rewards and claim instructions are shown only on their result page and private result link.
- They are kept until the run's data are deleted: when its period ends, or sooner through "Delete data now" or an erasure request.

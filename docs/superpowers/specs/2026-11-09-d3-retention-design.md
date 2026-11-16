# D3 Retention: automatic deletion, archive, targeted deletion

Marks: **[user]** decided by the user in this design, **[docs]** already in `docs/_architecture`, **[call]** the designer's choice, open to correction.

## Why

Since C3 a run records how long its data are kept, and the public privacy page promises deletion "in a later version". Nothing deletes anything today, so nicknames, e-mails, answers and photos pile up for ever. D3 keeps that promise (FR-34, AC-14) and gives an organiser two ways to delete sooner, one of them for a person who asks to be erased. Every deletion leaves a trail an organiser can show.

## Goals

- Personal data of a run disappear on their own after the run's period, without an admin doing anything. **[docs]**
- What is worth keeping about a past run survives as an anonymous summary. **[user]**
- An admin can delete a whole run's data now, and can act on an erasure request across runs. **[user]**
- Every deletion, automatic or manual, is visible in one place in the administration. **[user]**
- Nothing that was already past its period when D3 arrives is deleted without an admin confirming it. **[user]**

## Non-goals

- Deleting one participant from the run page. Not chosen; the erasure request covers it. **[user]**
- Backup tooling and backup retention (D5). **[docs]**
- Rate limits on the new pages (D5). **[docs]**
- E-mail notices of any kind; the system sends no e-mail. **[docs]**
- The complete FR-35 privacy notice beyond correcting what D3 makes untrue. **[call]**
- Deleting quizzes, revisions or runs themselves. Only the data a run collected. **[call]**

## Anti-goals

- A personal value in `audit_event`, `retention_job`, a log or an event payload. **[docs]**
- A deletion that blocks because rewards are unclaimed or answers ungraded. The admin was offered that block and did not take it. **[user]**
- Silent irreversible deletion of old data on the first pass after upgrading. **[user]**
- Deletion logic in the kernel, or a second code path for manual deletion. **[docs]**
- A run or the participant-facing pages crashing because the rows behind them are gone. **[call]**

## Behaviour

### When a run is due

- The period counts from `closed_at`. **[docs]** A run is due when `closed_at + period <= now`, its period is not permanent, and it has no deletion recorded. **[docs]**
- A run that never closed has no clock. **[call]** A run past its deadline that has not been settled yet is settled first with the existing logic in `run_schedule`, so the job sees its true `closed_at`. **[call]**
- Test runs (`Kind.TEST`) are skipped by the job and keep their own lifecycle behind the test link (ADR-0044). They do count in an erasure search. **[call]**
- Profile `none` runs are processed like the others: only leftover unsubmitted attempts can remain. **[call]**

### The job

- New compose service `jobs`, sharing the app's image and volumes, runs `python manage.py jobs`: a Python loop that makes one retention pass per hour. No cron daemon in the image, no new dependency. **[user]**
- The pass is also a command of its own, `python manage.py retention`, for running by hand or from a host's cron. **[user]**
- Each run is processed in its own transaction, in small batches so a live quiz is not starved of the single SQLite writer. **[call]** A run is claimed by a conditional update so two passes cannot process it twice. **[call]** A failure on one run is logged by run id and does not stop the others. **[call]**
- Files are removed after the commit. A file that could not be removed is picked up by the sweep of the next pass. **[call]**
- Each processed run writes one `retention_job` row and emits `retention.executed`. **[docs]**

### What deletion does to a run

One function, used by the job and by "Delete data now". **[docs]**

Deleted: all `attempt` rows of the run in any status including unsubmitted, their answers, hidden answer values and assigned questions; `participant` rows (names, e-mails, cookie hashes); `reward_entitlement` rows; participant photos, and photo files no answer refers to any more **[docs]**; `export_job` rows and files that name this run, or its quiz with all runs (TD-067) **[docs]**.

Kept: the run record, its revisions and reward rules; `draw` and `draw_entry` with `participant_id` cleared and the pseudonym left in place (ADR-0053) **[docs]**; the admin's `audit_event` history **[docs]**; the summary below **[user]**.

Summary, computed from the existing statistics in the same transaction just before the rows go, and stored on the run: participants, started, submitted, unsent, average, percent, per-revision summary, and per-question statistics only where the profile kept every answer. **[user]** Statistics and the comparison of runs read it for a deleted run instead of recomputing. **[call]**

Then the run moves to `ARCHIVED` and carries a label "Data smazána" / "Data deleted" with the date. **[user]** It can still be restored from the archive, but the data do not come back, and its period can no longer be changed. **[call]** The job and "Delete data now" skip a run with deletion recorded. **[call]**

After deletion, the public scoreboard, public archived results (ADR-0031) **[docs]**, the walkthrough and private result links show the same friendly "not available" state as other unavailable pages, without an error page. **[call]**

### Runs already past their period, and shortened periods

- The D3 migration marks every run that is already due as **held**. The job never deletes a held run. **[user]**
- The page "Deletion history" lists held runs above the history. An admin confirms the list once; confirmed runs are deleted on the next pass. Extending a held run's period past now clears the hold. Without a confirmation held runs stay for ever. **[user]**
- Shortening a period so the run is due at once needs a confirmation in the form, which names the consequence. Without it the period does not change. With it the run is deleted on the next pass. **[user]**
- A run that becomes due later in the normal way is deleted automatically with no confirmation. **[user]**
- Lengthening a period is allowed at any time until deletion. **[docs]**

### Manual deletion

Both ways need a confirmation that states what will be deleted and that it cannot be undone. **[call]**

- **Delete data now**, on the page of a closed or archived run: same result as expiry. Refused on a scheduled or open run. **[user]** for the action, **[call]** for the refusal.
- **Erasure request**, a page in the administration: search across all runs by e-mail, or by nickname. **[user]** An e-mail search compares the normalised address. **[call]** A nickname search compares `name_key`, and the admin ticks the rows meant because a nickname can belong to different people. **[call]** Results show the quiz, run, nickname and e-mail, in the logged-in administration only, and are not cached. **[docs]**
- Erasure deletes the chosen participants with their attempts, answers, photos and entitlements. Draw entries keep the pseudonym. **[docs]** The rest of the run stays and the run is not archived. **[call]** It works on a run in any state; an in-progress attempt of that person simply ends. **[call]**
- Export files naming an affected run are deleted as above. **[call]**
- An attempt with no participant row (a run that sets no cookie and asks no name) cannot be found by an erasure search, because nothing ties it to a person. Such an attempt's photo can still be removed by an admin as today. **[call]**

### Exports and deletion

- A queued or running export that names an affected run is ended as failed, and its later write is refused, so a file cannot appear after the deletion. **[call]** This adds a method to `ResultsExporterProvider`. **[call]**
- A deleted run in a new export is treated like profile `none`: only the count of submitted attempts. **[call]**

### The trail

- Every automatic deletion, "Delete data now" and erasure writes a `retention_job` row and an `audit_event`: who ("automatic" or the admin), when, which run, and how many rows of each kind. **[user]**
- An erasure by e-mail also stores an HMAC-SHA256 of the normalised address, keyed from the server secret with a purpose label of its own. The address is never stored. **[user]** Typing an address into the page answers whether and when it was erased, and by whom. **[user]** No free-text reason exists, so no name can get into the trail that way. **[user]** An erasure by nickname stores counts only. **[call]**
- A new page, **Deletion history** (`/admin/retention`), lists all of this, newest first, with held runs above; the run page links to its own row. **[user]** The history is kept for ever, because it holds no personal data. **[call]**

### Seeing the date

The run page and the list of runs show the date of deletion for a closed run with a period. Within 14 days of it the date changes colour and gains a text such as "za 9 dní", so colour never carries the meaning alone. **[user]** No banner and no dashboard item. **[user]** The colour meets WCAG AA in each palette. **[call]**

### Settings

No new setting: the hourly interval and the 14 days are constants. **[call]** The provider's manifest declares `settings: []`. **[docs]**

## Constraints

- A provider `local-retention` in `app/providers/retention/` behind a `RetentionProvider` contract. **[docs]** The contract does not exist yet in `app/contracts/__init__.py`, although `EXACTLY_ONE` already names `retention`, so it is added here and passes the shared contract tests in `tests/contracts/`. **[call]**
- Deleting export jobs goes through the `csv_io` provider's contract, not an import of it. **[docs]**
- The sweep of photo files looks only at `MediaAsset` rows with `private=True` that no `AttemptAnswer.asset_id` refers to and that are older than one hour, so it never touches an admin's image or a photo being submitted right now. **[call]**
- `Attempt.participant`, `Attempt.run`, `Attempt.replaced_by` are `PROTECT`, so the order of deletion matters, and `replaced_by` chains must be untied first. **[call]**
- The `jobs` service has the same hardening as `app`: non-root, `no-new-privileges`. **[docs]**
- UI texts in cs, en and uk; "běh", not "kolo". **[docs]**
- Docs in English; new ADR-0056 covers the job, the summary, held runs and the e-mail fingerprint; `docs/privacy.md` is corrected where it says "until D3", and gains the fingerprint. **[docs]**

## Risks

- Irreversible by design. A bug in "due" deletes real data, so that function has the most tests, including boundary times and permanent periods.
- The fingerprint depends on the server secret. Rotating the secret makes earlier fingerprints unverifiable, while the rest of the row stays. Documented in `docs/deployment.md`. **[call]**
- A summary of a run with one or two attempts reveals that person's score to an admin. Accepted: it holds no identity. **[call]**
- A downloaded export and a backup are outside this mechanism. **[docs]**
- Roadmap risk: backups must not restore deleted data indefinitely. Stays with D5. **[docs]**

## Left to the builder

- Field names on `quiz_run` for the summary, the deletion date and the hold, and the extra columns of `retention_job` (trigger, admin, fingerprint).
- Batch size, loop sleeping and clean stop on SIGTERM.
- The contract's exact method names.
- Where in the admin navigation the page sits, and the layout of the confirmation pages.

## Verification

New acceptance criteria from AC-110, each named by a test:

- AC-110 Due: a run past its period is processed; one a second short of it, permanent, never closed, held or already deleted is not.
- AC-111 What goes: after deletion no participant, attempt, answer, entitlement, photo or export file of that run remains; the run, revisions, reward rules and draw history with pseudonyms remain.
- AC-112 Summary: statistics and comparison show the same numbers before and after deletion; per-question figures appear only where the profile kept answers.
- AC-113 After: the run is archived with the label, can be restored without data, refuses a period change, and public scoreboard, private link and walkthrough give the unavailable page, not an error.
- AC-114 Held: runs due at migration are held and untouched by the job until confirmed; extending clears the hold; a period shortened into the past needs a confirmation.
- AC-115 Delete now: same result as expiry through the same code path, refused on an open run, audited.
- AC-116 Erasure: finds a person across runs by e-mail and by nickname, deletes only chosen rows, leaves the other participants, keeps draw pseudonyms.
- AC-117 Trail: every deletion has a history row and an audit event with counts and no personal value; an erased e-mail is confirmed by retyping it; the address is nowhere in the database.
- AC-118 Date: the date is shown, and within 14 days changes colour and shows the days left.
- AC-119 Job: `manage.py retention` and the `jobs` service make a pass; one run failing leaves the others processed; two passes do not double-process a run.

`make quality`, `make smoke` with the `jobs` service healthy, and `kvizotron-browser-walkthrough` on a new quiz in `kvizotron-browser`, whose existing data stay.

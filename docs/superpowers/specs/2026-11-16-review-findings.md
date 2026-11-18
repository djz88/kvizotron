# Kvízotron — repository analysis, 2026-11-16

## 1. Status against the roadmap

Done (per `docs/_architecture/roadmap.md` and verified by tests): stages A–D, milestones A1–A4, B1–B6, C1–C5, C4.5, D1–D5, the Quiz types addendum (ADR-0062) and project B "test add-ons" (ADR-0063). 176 ACs defined, no milestone missing.

Verification today: `make lint` OK (ruff, mypy 201 files), `make test` 5480 passed, 4 skipped (3:48 min), `make smoke` OK (all checks PASS, exit 0).

What remains before 1.0 (the roadmap and CLAUDE.md say the same):
- Release checks: `make load`, the restore drill, a browser walkthrough (this document partly covers it).
- TD-008: CI has never run on GitHub. The release gate is unproven.
- Triage of technical debt: 70 OPEN items in `TECH_DEBT.md`.
- Out of scope for 1.0 (LATER): Google Sheets, video question, more themes, SSO, e-mail, vouchers, JSON export.

Inconsistencies in the repository:
- The working tree has 42 changed `.mo` files with no content change; `make messages` generates them non-deterministically (timestamp). The tree is permanently "dirty".
- Untracked files in the root: `report.md`, `kvizotron_v4/`, `tmp-old/` (9 MB), `.superpowers/`, `kviz_eu_cr_*`, `kv_z_17_*`. They belong in `.gitignore` or gone.

## 2. Browser walkthrough

Procedure: a separate stack `kvizotron-review` (ports 28080/28443, clean volumes, admin `review`), Playwright + Chromium headless. Views: admin 1280 px light cs; participant 390 px dark uk; keyboard 1280 px cs. Created the quiz `rev-walk` with 3 questions (choice, number, matching), published it, opened a run, played it, switched the scoreboard on, ended the run. The `kvizotron-browser` stack was left untouched (rebuilt from the current code, but the login expired).

Passed without error: creating a quiz, the editor for three question types, the change overview, start, playing by questions with the progress indicator, submit, result, scoreboard (public, projector, phone), closing a run, the pages Runs/Grading/Test links/Revisions/Rewards/Export/Banks/Admins/Deletion history/Import/Modules/Preview. The console had no JS errors, no 5xx.

Findings (participant):
- P1 Keyboard: after "Start" the page loses focus (activeElement = body, Tab jumps to the footer). After "Next" focus is correctly on the question section. Fix: after the HTMX swap, focus the heading "Question 1 of N" (`tabindex=-1`, `focus()`).
- P2 Submitting without answers goes through without a warning (result 1/3). Fix: a confirmation "N questions without an answer" before submitting.
- P3 The quiz page with an ended run returns HTTP 404 (`public.py:169`). The browser logs it as an error; shared links and monitoring see it as a nonexistent page. Consider 200 (or 410).
- P4 On a phone the scoreboard falls apart into pairs "Place 1. / Name Player 2 / Points 3/3", every table row a card. Unreadable with 50 participants. Fix: a compact row "1. Player 2 · 3/3 · 100 %".
- P5 A result without a scoreboard offers only "Back to the quizzes". It lacks "Show answers" (when the reveal is allowed) and an explanation of why there is no more.
Findings (admin):
- A1 "End the run" exists twice: the button in the header goes through a confirmation (`run_close` GET), the form at the bottom of the run page (`run.html:193`) ends the run immediately without confirmation. Unify on the confirmation.
- A2 New quiz: "Identifier in the address" is required and has no hint, nothing is prefilled from the title; all languages are unticked and labelled by the codes `cs/en/uk`; "Quiz type" is collapsed. Fix: derive the slug from the title, tick the default language, show language names, expand the type (it is the most important choice).
- A3 The change overview on first publication lists every field with "Before –" (3 questions = 4 screens). For the first revision a summary is enough: "3 questions, 3 points, languages cs, uk".
- A4 The run page is 4300 px tall: QR, rewards, scoreboard (10 selects), statistics, participants, attempts, export, deadline, time. The "Deadline" field sits under the heading "Export". Three different Save buttons. The "Sections" panel helps, but tabs would be more readable.
- A5 The quiz settings are 6500 px tall, three independent forms with three "Save" buttons; the "Quiz type" select shows "Practice" even for a quiz without a type (it looks like a chosen type).
- A6 Question forms: 6 option rows × (cs, uk, image, address, description ×2) = 48 fields at once. Hide the image for an option behind "Add an image".
- A7 The Modules page: for a plugin without which the app does not work there is the text "The app does not work without the module scoring.basic" instead of a button. A locked button with a tooltip would be better.
- A8 Missing CSRF on `start` and `resume` (`play.py:317, 376`, `csrf_exempt`). Intentional (a participant without a session), but a foreign page can start an attempt in another person's browser. Low risk, document it in `security.md`.

## 3. Code review — bugs

Refuted: both agents reported bypassing the limits through a spoofed `X-Forwarded-For`. Empirical test on the stack: the 6th attempt with a different XFF got 429. Caddy drops an untrusted XFF. Recommendation: add this test to `deploy/smoke.sh` so it stays true.

Confirmed (ordered by impact):
1. `app/api/play.py:196-201, 448-459` — `allow()` and `record()` as two separate actions, concurrent requests from one address get past the limit. `rate_limit.try_acquire` already exists and login uses it. Use it here too.
2. `app/api/admin_quizzes.py:690-745` — `quiz_publish(start=1)` and `run_open` do not catch `results.ResultConflict`, `rewards.RewardConflict`, `RequirementUnmet` → HTTP 500 instead of an explanation. `admin_runs.py:308, 372` does it right. A shared error mapper for opening a run.
3. An archived quiz is not read-only (`domain.md:110` promises it): `admin_rewards.py:460, 486, 624`, `admin_grading.py:298, 321, 342`, `admin_runs.py:501, 617, 839` have no `ensure_editable`. One can draw, cancel entitlements and change grades on an archived quiz. One check in the domain entry points.
4. `app/domain/attempts.py:759` — `events.emit("attempt.submitted")` runs inside an atomic block with `with_retry`; on "database is locked" the block is repeated and the event goes out twice. Use `transaction.on_commit`.
5. `app/domain/rewards.py:646-672` — `grant_manual` does not verify a submitted attempt; only the UI list does. A hand-built POST grants a reward to a participant without an attempt.
6. `app/api/admin_settings.py:20-23`, `admin_forms.py:894-917` — saving global settings and branding in separate transactions; an error in the middle leaves half of it saved and the form reports an error. Wrap in `transaction.atomic`.
7. `app/domain/authoring.py:660`, `admin_quizzes.py:318` — `quiz.save()` of the whole object overwrites `archived_at` and `quiz_type` with a stale value when two admins race. `save(update_fields=...)` as in `quiz_types.py:213`.
8. `app/domain/heartbeat.py:132-151` — `jobs_healthy()` ignores the age of the `jobs` heartbeat and treats a damaged pass record as healthy. The service healthcheck can lie.
9. `deploy/compose.yaml:33-53` — no `stop_grace_period`; Docker kills `app` after 10 s, gunicorn has a graceful 30 s, `jobs` may be running a backup (related to TD-072).
10. `app/settings.py:18` — `SECRET_KEY` accepts any non-empty string ("x"). Reject short values.
11. `app/api/admin_users.py:133-146` — changing the e-mail of an unknown admin silently succeeds (update returns 0).
12. `app/domain/results.py:348-362` — anonymous numbers "Participant N" are computed from live rows; erasing one participant renumbers the others. The docstring claims the opposite. Store the number at creation.
13. `app/domain/attempts.py:455-482` — `_replacement` does not call `_require_modules` when switching revision; with a plugin turned off an attempt is created that then gives 503.

Probable (verify with a test):
- `app/kernel/lifecycle.py:84-99` — `blockers()` outside the transaction, concurrent opening of a run and turning off a plugin.
- `app/domain/authoring.py:556` — `ensure_editable` before the atomic block, concurrent archiving.
- `app/providers/media_local/remote.py:45-49` — NAT64 prefix `64:ff9b::/96` is not blocked (only on NAT64 networks).
- `app/api/run_clock.py:23-27` — `settle()` on every request; with a held plan a few extra queries on every request.

Performance (confirmed N+1, with 50 participants it does not hurt, with dozens of quizzes it does):
- Quiz list: ~10 queries per quiz and a full bank load for every draw (`quiz_state.py:69-88`, `banks.py:239-246`).
- Editor: a query for the folder and the whole bank for every draw row (`admin_quizzes.py:163-175`).
- `results.place_of` recomputes the whole order without a cache on every submit (`results.py:631-645`); the table has a 5 s cache, the place does not.
- `participants.begin()` runs up to 3× per start (`play.py:87`, `attempts.py:221`).
- `registry.keys()` queries `is_enabled()` for every port (`registry.py:56-58`) and `ModuleGateMiddleware` queries on every request.
- Exporting a quiz/bank with images builds the ZIP in memory inside the request (`admin_export.py:41-58`); the results export has a background job.

## 4. Code review — simplification

- Duplicate helpers across `admin_*.py`: `_admin` (3×), `_uuid` (2×), `_plain` (2×), `_refusal` (4×), `_locale` (2×), `_back` (3×), a confirmation page inline 7×. One module `admin_common.py`.
- Walking the `replaced_by` chain written 4× (`attempts.py` ~141, ~286, 784; `participants.py:161`). One `_current_of()`.
- `StartedAttempt(...)` built 3× (`attempts.py:152, 260, 281`).
- `needs_participant` / `begin` / `start_decision` / `can_resume` — four wrappers of one decision; keep `begin`.
- `results.kept()` called 4× in one request (pass_mark, rewards.refresh, played_result, begin); memoize.
- Local imports because of cycles (`participants.py:111, 170, 242, 289`; `attempts.py:177`; `draws`↔`rewards` TD-049) — a sign of a bad layer cut.
- Two parallel tables of setting placement: `admin_forms.BRANDING_PLACES/COLOUR_PLACES` vs. `admin_view.CHILD_OF/COLUMNS`.
- Long functions: `quiz_types._plan` (79 lines), `admin_banks._bank_page` (73), `admin_runs._run_context` (72), `admin_forms.__init__` (62). Files over 800 lines: `admin_forms.py` 1162, `play.py` 936, `admin_runs.py` 861, `authoring.py` 849.
- The kernel knows the quiz vocabulary: a fixed list of events (`kernel/events.py:12-21`) and a regex of upload routes (`kernel/middleware.py:10-16`). According to `app/kernel/CLAUDE.md` it should not. Register them from modules.
- Contracts: a `runtime_checkable` Protocol checks only member names (`registry.py:29`); a wrong arity passes. `ExporterProvider.write` takes bytes, `ResultsExporterProvider.write` paths. Unify.
- Tests: 274 files, 50 212 lines, ~3 670 tests; 18 files over 500 lines (`test_restore.py` 964, `test_choice.py` 953); ~28 duplicate helpers (`a_run`, `who`, `finish`, `make_quiz`); `conftest.py:18` writes to `registry._ports` directly; `events._handlers` and `lifecycle._usage_checks` are not reset between tests; 4 time-dependent tests (`test_jobs_heartbeat.py:171`, `test_login_limit.py:118`).

## 5. Operations and release

- Compose: no `read_only`, `cap_drop`, `pids_limit`, `mem_limit`, log limit; the secret as env (visible to `docker inspect`) instead of `secrets:`.
- CI: no `timeout-minutes`, `concurrency`, dependency audit (`pip-audit`/`uv audit`), image scan. Dependabot only opens PRs.
- `Makefile:63` `make secrets` with `--all-files` on a hook that reads only staged changes anyway. Delete the flag or fix the text.
- `settings.py:110` claims uploads stay in memory up to the body limit; above 16 MB Django spools to the container disk. Fix the comment or `TMPDIR`.
- Backups only in a local volume, unencrypted; an off-host copy is only a recommendation in `deployment.md`.
- Translations: `app/api/locale/uk` has 306 untranslated strings (the admin UI is intentionally only cs/en; the public pages in uk were translated completely). Write the intent into the docs or trim the catalogue.

## 6. Recommended order before 1.0

1. Get CI running on GitHub (TD-008), add the XFF test to smoke.
2. Fix items 1–8 from part 3 (start each with a test).
3. UX: A1, A2, P1, P2 — small changes with a big impact on first impressions.
4. Decide TD-101 and TD-036 (live reading of settings by an open run) — they threaten the fairness of the contest.
5. Cleanup: `.mo` deterministic or out of git, untracked files, `admin_common.py`, splitting `admin_forms.py` and `play.py`.
6. `make load` and the restore drill from `deployment.md`.

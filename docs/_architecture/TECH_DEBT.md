# Technical Debt

Central list of known gaps and deviations from the architecture. This is for what is knowingly
postponed; resolved items are moved to TECH_DEBT_archive.md after some time.

## Format

- Open item: `### TD-NNN Title — OPEN`, followed by a description, a `file:line` reference and a proposed solution.
- Resolved item: `### TD-NNN Title — ✅ RESOLVED (YYYY-MM-DD)`, moved under `## RESOLVED`.
- `## OPEN` is the last section before `## RESOLVED`; new sections go above it.

## OPEN

### TD-022 Automatic submission is not repeated after a server error — OPEN
- Where: `app/api/assets/countdown.js:138`
- Effect: the page repeats it only after a network error. A 5xx or a connection that hangs leaves the page waiting, the time runs out, and the attempt is lost
- Solution: also repeat on `htmx:responseError` with status 500 or more and on `htmx:timeout`, and give the request a timeout

### TD-023 Run status and time zone are read more often than needed — OPEN
- Where: `app/api/run_clock.py:13`, `app/domain/clock.py:37`
- Effect: `/media/` requests and the 30 s asks for the time also run the two schedule queries, and every shown time reads the zone from the database. Cheap at about 50 participants, but it adds up on long lists
- Solution: skip `/media/`, and read the zone once per request

### TD-024 A plan stuck past its deadline leaves an empty ended run — OPEN
- Where: `app/domain/run_schedule.py:68`
- Effect: a plan held back by unmet requirements until after its deadline opens and closes at once, so the list shows an ended run nobody could play
- Solution: leave it planned with a message for the admin once its deadline has passed

### TD-025 Second occurrence of an ambiguous time moves on saving — OPEN
- Where: `app/domain/clock.py:41`
- Effect: a time in the repeated hour of a clock change, stored as its second occurrence, shows without that distinction and moves an hour earlier when the form is saved again. Only a value set outside the form can be one, as the form always takes the first occurrence
- Solution: keep the stored value when the field was not changed

### TD-008 CI has not run on GitHub — OPEN
- Where: `.github/workflows/quality.yml`; the repository has no remote yet
- Effect: the workflow passes actionlint and its commands pass in a clean Python 3.15 container, but it has never run on a GitHub runner.
- Solution: push to GitHub and confirm that both jobs pass.

### TD-013 Installation modes no network / normal that derive security settings — OPEN
- Where: `allow_internal_image_addresses` in `app/providers/media_local/manifest.py`, `external_image_mode`
- Effect: an installation in a closed network sets each related setting by hand, and its quizzes warn about addresses it can never reach
- Solution: a global mode "no network / normal" from which these settings and their defaults follow

### TD-014 Question categories — OPEN
- Where: `app/domain/question_import.py`, where a category column is reported as unused; `kv_z_17_listopad_st_tnost_a_evropa.md` has one per question
- Effect: categories in a file are lost on import, with a note in the report
- Solution:

### TD-015 Photo files left behind when storing fails midway — OPEN
- Where: `app/api/play.py:337` (`with_files`), `app/providers/media_local/provider.py:236` (`_saved`)
- Effect: if a later photo of one submission fails with anything but `ImageRefused`, such as a full disk or a locked database, the photos already written stay on the volume with no row pointing to them. `_saved` also writes the file before its row, so a failed save leaves one file. Nobody sees them, but they take space
- Solution: let `with_files` append to a list the caller owns and remove it on any exception; remove the file in `_saved` when the row cannot be saved

### TD-016 Walkthrough loads all answers on every request — OPEN
- Where: `app/domain/walkthrough.py:60` (`available`), `:113` (`photo_for_public`), `app/api/public.py` (`_walkthrough_url`)
- Effect: `available` loads every answer row of the run, on each page view of an ended quiz when answers are not public and once per image of the walkthrough, so a gallery of 30 photos loads them 30 times
- Solution: decide from question settings without loading answers where possible, and keep the result for the length of a request

### TD-017 Closed quiz page fails when a question type's module is uninstalled — OPEN
- Where: `app/domain/walkthrough.py:74` (`_plugin`), called from `available` and `of_run`
- Effect: after a question type's module is uninstalled, the public page of an ended quiz answers 500 when its answers are not public, and the walkthrough answers 500 in any case
- Solution: catch `UnknownPort` as `_own_answers` in `app/api/public.py` does, and leave such a question out

### TD-018 Number answer with a thousands separator is graded wrong without a message — OPEN
- Where: `app/plugins/questions/number/plugin.py:39` (`parse_number`)
- Effect: a comma is a decimal separator as the docs say, so `1,000` reads as 1 and is graded wrong, with only the hint under the field to warn about it
- Solution: ask to confirm or show a message for exactly three digits after a separator, in the page's script and without changing what the server accepts

### TD-019 Stale tab posting a photo form to a switched attempt gets a bare 415 — OPEN
- Where: `app/api/play.py:99` (`accepts_upload`), `:113`
- Effect: after an attempt was switched to a new revision, an old tab still holding its photo form posts to the switched attempt and gets a bare 415, instead of the notice that the attempt was replaced
- Solution: admit multipart for a switched attempt too, store nothing, and let `submit` answer `attempt_switched`

### TD-020 Gallery question chips are not in quiz order — OPEN
- Where: `app/api/admin_grading.py:112` (`_gallery`)
- Effect: the links to questions with photos are sorted by question id, so with several photo questions they do not follow the order of the quiz. Cosmetic
- Solution: sort by position in the run's last revision, as `_questions` already lists them

### TD-021 Hand-crafted result photo address logs its token — OPEN
- Where: `app/urls.py:24`, the `uuid` part of `result_photo`
- Effect: `/v/<token>/photo/<not a uuid>` answers 404, and Django logs that with the path, so a token can reach the log. Only a hand-crafted address does this; pages never link to one
- Solution: take the last part as a string, and answer 204 for anything that is not a known id

### TD-026 MediaStorageProvider has no shared contract suite — OPEN
- Where: `tests/providers/test_media_local.py`, `tests/test_wiring.py:34`
- Effect: the project rule asks every module to pass a shared suite in `tests/contracts/`. `media_local` has only its own tests, so a second media provider would have nothing to prove itself against
- Solution: add `tests/contracts/media_storage.py` when a second provider is planned, and drop the exception

### TD-027 C2: name_key max_length 80 is short for 3x casefold expansion (e.g. ﬃ), harmless on SQLite — OPEN
- Where:
- Effect:
- Solution:

### TD-028 C2: start under forbid with a required name shows name_required before already_played — OPEN
- Where:
- Effect:
- Solution:

### TD-029 C2: a start POST without a cookie creates a Participant row each time; limit with D5 — OPEN
- Where:
- Effect:
- Solution:

### TD-030 C2: update_plan(rules=None) and RunPlanForm.rules() fall back to quiz rules for a missing field — OPEN
- Where:
- Effect:
- Solution:

### TD-031 C2: run page value_labels[value] raises KeyError for a stored rule value no longer offered — OPEN
- Where:
- Effect:
- Solution:

### TD-032 C2: plan form re-render echoes a typed but unsaved access code — OPEN
- Where:
- Effect:
- Solution:

### TD-033 C2: missing tests - locked-start resume with forged cookie and used/submitted modes, enter_code CSRF path, lenient submit of ABANDONED — OPEN
- Where:
- Effect:
- Solution:

### TD-034 C2: fill-in name input on the result page is half width — OPEN
- Where:
- Effect:
- Solution:

### TD-035 C2: _no_store in play.py duplicates part of public._private; quiz_page lazily imported by play — OPEN
- Where:
- Effect:
- Solution:

### TD-036 Answers visibility is judged by the quiz's live profile, not the run's frozen profile — OPEN
- Where: app/domain/settings.py `visibility_conflict`, `answers_visibility`.
- Effect: Visibility is judged by the quiz's current profile while an attempt keeps the profile frozen at start. Harmless today because less is stored than visibility suggests.
- Solution: Judge visibility by the run's frozen profile.

### TD-037 resume.js drops the copy after submit by a heuristic (200 on /submit and no form) instead of an explicit header on success — OPEN
- Where: app/api/assets/resume.js, the `htmx:afterRequest` handler.
- Effect: After a submit the copy is dropped when the answer is 200 on `/submit` and no form is left; a changed page could leave the copy behind or drop it early.
- Solution: Send an explicit header on a successful submit, as `X-Kvz-Drop-Copy` does for refusals.

### TD-038 resume.js saves an empty copy at swap before restoring (kvz:step fires first); a tab killed in that moment loses the copy — OPEN
- Where: app/api/assets/resume.js, `htmx:afterSwap` and `kvz:step`.
- Effect: `kvz:step` fires before the restore and saves an empty copy first; a tab killed in that moment loses the copy.
- Solution: Save only after the restore has run.

### TD-039 No automated tests for resume.js and the flow.js events; only the browser walkthrough covers them — OPEN
- Where: app/api/assets/resume.js, app/api/assets/flow.js.
- Effect: No automated test covers them; only the browser walkthrough does.
- Solution: Add a small JS test harness, or test the scripts in a headless browser.

### TD-040 privacy.md restates the stateless refusal list and the 24-hour rule instead of linking ADR-0050 — OPEN
- Where: docs/privacy.md.
- Effect: It restates the stateless refusal list and the 24-hour rule, so they can drift from ADR-0050.
- Solution: Link ADR-0050 instead of repeating.

### TD-041 Public scoreboard response has no Vary: Accept-Language, Cookie — OPEN
- Where: app/api/scoreboard.py, `_cache`.
- Effect: Without a cookie the answer is `public, max-age=5`, but its language can come from Accept-Language and its "you" mark from the cookie; a shared cache keyed on the URL could serve another language or drop the mark. The stack has no shared cache today.
- Solution: Add `Vary: Accept-Language, Cookie`, or answer `private` everywhere.

### TD-042 Own place on a scoreboard counts unlisted participants and reveals their number — OPEN
- Where: app/domain/results.py, `place_of`.
- Effect: With unnamed participants left out, "place k of N" still counts them, so a participant learns how many rows are hidden.
- Solution: Decide whether N counts only listed rows; ADR-0051 keeps the gap in ranks either way.

### TD-043 Shared tie place is rare with the default second sort; the setting needs a help line — OPEN
- Where: app/plugins/results/ranking.py, `rank`; the setting `tie_break_policy`.
- Effect: Ties are broken by the second sort first, and the default sorts by submission time, so `shared` places appear only for identical times. Admins may expect shared places for equal scores.
- Solution: Add a help line to the tie setting, or offer "none" as a second sort.

### TD-044 Run statistics queries grow with the number of attempts — OPEN
- Where: app/domain/run_stats.py (`_questions`, `_submitted`), app/domain/participants.py (`attempt_rows`).
- Effect: The run page loads every submitted attempt and answer into memory; fine for about 50 participants, slow for thousands.
- Solution: Aggregate in SQL (`Avg`, `Count`) and page the attempts table.

### TD-045 C4.5: a quiz Save in Basic clears an advanced override another admin set meanwhile — OPEN
- Where: app/api/admin_quizzes.py `quiz_settings`, the loop that sets overrides.
- Effect: The quiz form posts only shown fields. If admin B sets an advanced override while admin A has the page open in Basic, A's Save sees the hidden field empty and clears B's override. Unlikely with a few admins.
- Solution: Change only keys present in the POST, or compare against the values the page was drawn with.

### TD-046 C4.5: Questions per page shows in Basic also when the quiz is not in pages mode — OPEN
- Where: app/domain/settings.py, `PAGE_SIZE` with `level=BASIC`.
- Effect: Basic shows "Questions per page" on every quiz, also when it is not in pages mode, with the help "Only for pages".
- Solution: Show it in Basic only when the navigation resolves to pages.

### TD-047 C5: rewards ignore the scoreboard revision mode when choosing the official attempt — OPEN
- Where: app/domain/results.py `official_attempt`, app/domain/rewards.py `refresh`.
- Effect: In a run with several revisions the reward uses the best or first attempt over all revisions, while the scoreboard may show one table per revision or only the latest.
- Solution: Decide whether rewards follow `revision_mode` (ADR-0053 states the current rule) and pick the official attempt the same way the board does.

### TD-048 C5: entitlement actions on archived runs and automatic changes without audit — OPEN
- Where: app/domain/rewards.py `hand_over`, `cancel`, `refresh`; app/api/admin_rewards.py `entitlement`, `reward_grant`.
- Effect: An admin can hand over, cancel or grant on an archived run. Automatic grants and cancellations keep only the row's reason and time, not an audit event.
- Solution: Refuse changes on archived runs if wanted, and record automatic changes in `audit_event` with ids only.

### TD-049 C5: draws uses private helpers of rewards; module-level import cycle rewards and authoring — OPEN
- Where: app/domain/draws.py (`rewards._figures`, `_grant_draw`, `_cancel_draw`, `_locked_run` called twice); app/domain/rewards.py and authoring.py import each other at module level.
- Effect: Works today; a refactor can break it, and private names hide a real interface.
  Four lazy or back imports now hold the cycles together: attempts and rewards, participants and rewards, rewards and draws, and grading to rewards (rewards to results to draws to grading).
- Solution: Make the three helpers public, drop the second run check, and move one import into the function. Longer term, one "after an attempt changes" hook that the domain calls in the transaction (not an event, which dispatches on commit) would replace the four cross-imports.

### TD-050 C5: one reward form shows threshold and draw fields for every kind — OPEN
- Where: app/api/admin_forms.py `RewardRuleForm`, admin/_reward_rule_form.html.
- Effect: A rule form shows threshold, minimum, winners and alternates for every kind; help texts say which kind uses them.
- Solution: Group the fields by kind and show only the chosen kind's fields (without inline script).

### TD-051 C5: an IntegrityError from refresh is reported as a used submission key — OPEN
- Where: app/domain/attempts.py `_store`, the `except IntegrityError` around the submission transaction.
- Effect: A unique-constraint failure from `rewards.refresh` would be reported as `submission_key_used`. Unlikely under IMMEDIATE transactions, but it hides the cause.
- Solution: Narrow the handler to the submission key constraint, and add a query-count test for `refresh`.

### TD-052 C5: published winners reach the projector only on page load — OPEN
- Where: app/api/scoreboard.py and public/scoreboard.html: the winners section is outside the 15 s refreshed rows.
- Effect: On a projector left open, newly published winners appear only after a reload.
- Solution: Move the winners into the refreshed fragment, or refresh the section on its own.

## RESOLVED

### TD-001 Project purpose missing in README — ✅ RESOLVED (2026-11-05)
### TD-002 Installation steps missing in README — ✅ RESOLVED (2026-11-05)
### TD-003 Commands and API missing in README — ✅ RESOLVED (2026-11-05)
### TD-004 Development commands missing in README — ✅ RESOLVED (2026-11-05)
### TD-005 Security contact missing — ✅ RESOLVED (2026-11-05)
### TD-006 Makefile targets are placeholders — ✅ RESOLVED (2026-11-05)
### TD-007 CI is missing — ✅ RESOLVED (2026-11-05)

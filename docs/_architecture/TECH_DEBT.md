# Technical Debt

Central list of known gaps and deviations from the architecture. This is for what is knowingly
postponed; resolved items are moved to TECH_DEBT_archive.md after some time.

## Format

- Open item: `### TD-NNN Title — OPEN`, followed by a description, a `file:line` reference and a proposed solution.
- Resolved item: `### TD-NNN Title — ✅ RESOLVED (YYYY-MM-DD)`, moved under `## RESOLVED`.
- `## OPEN` is the last section before `## RESOLVED`; new sections go above it.

## OPEN

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

### TD-016 Walkthrough loads all answers on every request — OPEN
- Where: `app/domain/walkthrough.py:60` (`available`), `:113` (`photo_for_public`), `app/api/public.py` (`_walkthrough_url`)
- Effect: `available` loads every answer row of the run, on each page view of an ended quiz when answers are not public and once per image of the walkthrough, so a gallery of 30 photos loads them 30 times
- Solution: decide from question settings without loading answers where possible, and keep the result for the length of a request

### TD-019 Stale tab posting a photo form to a switched attempt gets a bare 415 — OPEN
- Where: `app/api/play.py:99` (`accepts_upload`), `:113`
- Effect: after an attempt was switched to a new revision, an old tab still holding its photo form posts to the switched attempt and gets a bare 415, instead of the notice that the attempt was replaced
- Solution: admit multipart for a switched attempt too, store nothing, and let `submit` answer `attempt_switched`

### TD-020 Gallery question chips are not in quiz order — OPEN
- Where: `app/api/admin_grading.py:112` (`_gallery`)
- Effect: the links to questions with photos are sorted by question id, so with several photo questions they do not follow the order of the quiz. Cosmetic
- Solution: sort by position in the run's last revision, as `_questions` already lists them

### TD-027 C2: name_key max_length 80 is short for 3x casefold expansion (e.g. ﬃ), harmless on SQLite — OPEN
- Where:
- Effect:
- Solution:

### TD-028 C2: start under forbid with a required name shows name_required before already_played — OPEN
- Where:
- Effect:
- Solution:

### TD-030 C2: update_plan(rules=None) and RunPlanForm.rules() fall back to quiz rules for a missing field — OPEN
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

### TD-052 C5: published winners reach the projector only on page load — OPEN
- Where: app/api/scoreboard.py and public/scoreboard.html: the winners section is outside the 15 s refreshed rows.
- Effect: On a projector left open, newly published winners appear only after a reload.
- Solution: Move the winners into the refreshed fragment, or refresh the section on its own.

### TD-053 D1: play error pages show the global branding — OPEN
- Where: `app/api/play.py` `_error`
- Effect: An error page during play (closed run, bad token) shows the global name, logo and colours instead of the quiz's.
- Solution: Pass `branding_quiz` where the caller knows the run; most of the 18 call sites do not, so thread the quiz through.

### TD-054 D1: palette and custom colours save in two steps — OPEN
- Where: `app/api/admin_settings.py`, `app/api/admin_quizzes.py` (settings save then `save_colours`)
- Effect: A failure between the two writes could leave `custom` without its colours; validation runs first, so it is unlikely.
- Solution: Wrap both writes in one `transaction.atomic()`.

### TD-055 D1: no Remove override for a quiz's custom colours — OPEN
- Where: `app/api/jinja2/admin/_branding_fields.html`, `app/domain/branding.py`
- Effect: After the quiz palette goes back to the global value, its stored colours stay; they are inert but the field shows as modified.
- Solution: Clear the quiz colours when the palette override is removed, or offer Remove override for them.

### TD-056 D1: branding resolution costs several queries per page — OPEN
- Where: `app/api/rendering.py` `page()`, `app/domain/branding.resolve`
- Effect: About 6–8 small queries per page; fine for ~50 participants on SQLite.
- Solution: Cache the resolved global row per request or with a short-lived cache; check in the D5 load test.

### TD-057 D1: footer details — OPEN
- Where: `app/api/rendering.py`, `tests/api/test_branding_pages.py`, `tests/api/test_admin_branding.py`
- Effect: Footer constants sit mid-file and the badge map is rebuilt per request; one footer test depends on whitespace; no test of the year in another time zone or of the 254-character limit in the form.
- Solution: Move the constants up, parse the paragraph text in the test, add the two tests.

### TD-058 D1: admins page edge cases — OPEN
- Where: `app/api/admin_users.py` `_change_email`, `app/domain/branding.py` `set_contact_email`
- Effect: A tampered `admin_id` shows its error nowhere; the domain `ValueError` for a bad e-mail is not translated (the form message is).
- Solution: Show a page-level message for an unknown account; raise a translated error.

### TD-059 D1: section panel polish — OPEN
- Where: `app/api/assets/sections.js`, `app/plugins/theme_default/assets/theme.css`
- Effect: Marking the current section can pick the wrong item for tall sections; an archived quiz's settings page leaves an empty right column.
- Solution: Mark the section nearest the top; drop the grid when the page has no panel.

### TD-060 D1: Makefile is generated by heimdall — OPEN
- Where: `Makefile`
- Effect: `env-update`, the pinned pre-commit and the uv version check are hand edits; regenerating the Makefile would drop them.
- Solution: Port the changes to the heimdall template.

### TD-061 D1: colour derivation tidiness — OPEN
- Where: `app/plugins/theme_default/colours.py`, `app/plugins/theme_default/assets/theme.css`
- Effect: The `darker` parameter shadows the `darker()` function, `PAIRS` is duplicated between the plugin and `tests/test_palettes.py`, and `.motto` is a generic selector.
- Solution: Rename the parameter, add a test that the two lists are equal, scope the selector.

### TD-062 Export: table_sink suite as mixin with test_* methods; ExportJobView.status as Literal; ExportTable columns/headers length check — OPEN
- Where: `tests/support/sheets_fake.py`, `tests/contracts/`, `app/contracts/` (`ExportJobView`, `ExportTable`)
- Effect: The table_sink suite is not a mixin with `test_*` methods, so a new sink cannot inherit it; `ExportJobView.status` is a plain `str`; an `ExportTable` with fewer headers than columns is accepted.
- Solution: Turn the suite into a mixin, type `status` as a `Literal` of the five statuses, check lengths in `ExportTable.__post_init__`.

### TD-063 Export: validate table names against SAFE_NAME; tidy outside the IMMEDIATE lock; skip tidy write lock on idle polls — OPEN
- Where: `app/providers/csv_io/results.py` (`_csv_name`, `_tidy`, `claim_next`, `jobs`)
- Effect: A table name is trusted to be a safe file name; `_tidy` deletes directories inside the IMMEDIATE transaction of `claim_next` and takes the write lock on every 2 s poll even when nothing changed.
- Solution: Check table names against `SAFE_NAME`, remove directories after the commit, skip the update when there is nothing to tidy.

### TD-064 Export: shared contract suite for ResultsExporterProvider before the D3 jobs container — OPEN
- Where: `tests/contracts/`, `app/providers/csv_io/results.py`
- Effect: `ResultsExporterProvider` is tested only through the CSV provider; a second implementation (the D3 jobs container) has no shared suite to pass.
- Solution: Move the provider tests that state the contract into `tests/contracts/` as a suite every implementation inherits.

### TD-065 Export: entitlements N+1 on attempt.revision; narrow except in question text; per-label locale fallback; draw admin column as login — OPEN
- Where: `app/domain/results_export.py` (entitlements, question text, headers, draws)
- Effect: Entitlements read `attempt.revision` per row (N+1); the question text helper catches a broad exception; a missing translation falls back per file, not per label; the draw file names the admin by id, not login.
- Solution: `select_related` the revision, narrow the except, fall back per label, show the admin's login.

### TD-066 Export: edge-case tests (personal file without confirmation, invalid bundle, unknown file, score run without photos); atomic restart against double submit — OPEN
- Where: `app/api/admin_results_export.py`, `tests/api/test_results_export.py`, `app/providers/csv_io/results.py` `restart`
- Effect: Edge cases (personal file without confirmation on ZIP, invalid bundle, unknown file, a `score` run without photos) have no tests; two quick restart submits can both create a job before the old row is deleted.
- Solution: Add the tests, delete the old row and create the new one in one transaction keyed on the old status.

### TD-069 Attempts table on the run page overflows on a phone — OPEN
- Where: `app/api/jinja2/admin/run_attempts.html:11`
- Effect: The attempts table (C3) is wider than the phone screen and scrolls the page sideways
- Solution: Use the `stack` table layout with `data-label` cells, as the other admin tables do

### TD-070 Runs table is 7 px wider than the page when a held run widens the status cell — OPEN
- Where: `app/api/jinja2/admin/runs.html`, `app/api/assets/`
- Effect: A held run's status cell with the deletion date makes the runs table 7 px wider than the page
- Solution: Let the status cell wrap or give it a maximum width

### TD-071 A deleted run's page still offers what no longer exists — OPEN
- Where: `app/api/jinja2/admin/run_scoreboard.html`, `app/api/jinja2/admin/run_export.html`, `app/api/jinja2/admin/prize_draw.html`, `app/domain/retention.py`
- Effect: The page of a deleted run still shows scoreboard settings and an export link; the draw page says it keeps no scores for a run that had them; a 64-character pseudonym overflows the draw Name column
- Solution: Hide settings and export for a deleted run, word the draw page by whether scores existed, and wrap or shorten the pseudonym

### TD-073 admin_retention reaches into private helpers of other modules — OPEN
- Where: `app/api/admin_retention.py:20`, `app/api/admin_runs.py`
- Effect: The view imports `_tab_page` from `admin_runs` across modules (the refusal is now the public `admin_common.refusal`); a malformed run id on the held form gives a generic message; a replacement theme must supply the `.deletion-soon` style or the warning is not visible
- Solution: Make the helpers public, give the malformed id a specific message and put `.deletion-soon` in the theme contract

### TD-077 D4: command to remove a module and reverse its migrations — OPEN
- Where: `app/kernel/management/commands/modules.py`; promised in `docs/_architecture/modules/kernel.md`
- Effect: an operator who removes a module package has no check that nothing needs it, and its tables stay behind
- Solution: a command that refuses while an active quiz or stored revision needs the module, and otherwise reverses its migrations

### TD-078 D4: refusal for a closed run does not say that archiving it lifts the block — OPEN
- Where: `app/domain/usage.py`, `reward_rule_usage` and `_LIVE`
- Effect: a closed run that is not archived blocks disabling `drawings.manual` or `rewards.threshold`, and the reason names only the run, so the admin does not learn what lifts it
- Solution: a reason text for a closed run that says archiving it lifts the block

### TD-079 D4: two concurrent module switches can write two audit events — OPEN
- Where: `app/kernel/lifecycle.py`, `set_enabled`
- Effect: the check runs outside the transaction, so two requests at the same moment can both pass and write two audit rows; the state itself stays right
- Solution: read the state again inside `transaction.atomic()` and return when it is already there

### TD-080 D4: module list ignores Czech collation and its buttons fill the column — OPEN
- Where: `app/api/admin_plugins.py`, `plugins_page`; `app/api/jinja2/admin/plugins.html`
- Effect: names starting with Č or Ú sort after Z, and each switch is as wide as its column, which makes the rows tall
- Solution: sort by a key that follows the admin language and give the switch a compact button style

### TD-086 D5: make load cannot tell 127.0.0.1 from 127.0.0.2 and cannot combine photo with reveal — OPEN
- Where: `tools/load_participants.py:402`, `deploy/load.sh` (the `load` quiz)
- Effect: measured on the `kvizotron-load` stack (the follow-up): the published ports are served by Docker's proxy, so every loopback source (127.0.0.1, 127.0.0.2) reaches Caddy as one address and shares one request-limit bucket, while a connection to the machine's LAN address keeps its source and is counted apart. The probe therefore proves only that a LAN source is counted apart and reports the loopback line as not measured; and a quiz with a photo question cannot use reveal after each question, because the application forbids the combination (a person must grade the photo), so the heaviest mode is run on two quizzes (`load` with photos, `reveal` without) and never together
- Solution: for the first half nothing in the application can change what Docker's proxy hides (a stack that publishes no port through the proxy would); if the combination becomes allowed, merge the two seeded quizzes. Until then the limits are documented in `docs/deployment.md`

### TD-088 D5: the Caddyfile test hardcodes gunicorn's keep-alive default — OPEN
- Where: `tests/test_deploy_headers.py:26`
- Effect: the test asserts that Caddy's `keepalive` is below 2, gunicorn's default, without reading what the `Dockerfile` starts gunicorn with, so adding `--keep-alive 1` to the `CMD` would pass the test while the proxy could again reuse a closed connection
- Solution: read `--keep-alive` from the `CMD` in the `Dockerfile` (default 2) and compare Caddy's value with it

### TD-091 D5 follow-up: a 429 at the deadline cannot be recovered by waiting — OPEN
- Where: `app/api/assets/countdown.js` (the 429 repeat), `app/api/play.py` (`_limited`, bucket `submit`)
- Effect: a 429 on the automatic submission repeats after `Retry-After`, which is always 60 seconds and so always after the limit, and the server rejects any send after the limit with `attempt_expired` (`attempts._check_still_valid`, no grace, [ADR-0025](adr/0025-deadline-boundary-second-semantics.md)). The attempt is lost, though the participant now sees the server's verdict. It needs more than the submit limit of 120 a minute from one address, for example a class of over 120 on one address finishing in the same minute. The repeats of the automatic submission make it likelier: every send counts toward the same bucket, so a shared address where each participant sends once and up to six more times after failures raises the volume well above the number of participants, and a very large group hitting the deadline together can meet 429
- Solution: do not count a repeat of an attempt that is still in progress in the `submit` bucket, or count only the first send per attempt, or raise the default; decide it with ADR-0025 in mind (no grace after the limit)

### TD-092 D5 follow-up: a hung request at the deadline is neither cut nor repeated — OPEN
- Where: `app/api/assets/countdown.js`
- Effect: a request that hangs when the automatic submission is sent is only ended by the browser or the network, so no repeat follows inside the margin. A request timeout was tried and removed: a cut request that the server still stores made the repeat get 410, and the participant was told the time had run out although the original committed
- Solution: a timeout together with a repeat that treats 410 as "maybe stored" and tries the stored-result path, or a server answer that reports a stored attempt for the key before the expiry check

### TD-093 delete_images is not exception-safe: a locked database in delete_image replaces the original error and skips the remaining ids — OPEN
- Where: `app/api/rendering.py` `delete_images` and `delete_image` of the media provider; predates the D5 follow-up
- Effect: `delete_images` runs after the transaction that forgot the assets and calls `delete_image` in a plain loop. When one call raises (for example a locked database), the exception replaces the error the caller was already handling and the remaining ids are not tried, so their files stay until the sweep finds them
- Solution: try every id, log the exception type only for each failure and raise once at the end (or return the ids that stayed), and let a caller that is already failing keep its own error

### TD-094 Quiz type: live game led by a host — OPEN
- Where: no such mode; every attempt runs at the participant's own pace (`app/plugins/quiz_flow/plugin.py:21`, `app/domain/attempts.py`). Left out of the quiz presets (2026-11-12) as too large for a preset
- Effect: a Kahoot-style game cannot be run. Missing: a host screen that moves all participants to the next question together; a time limit per question (only per attempt today, `attempt_limit`); points for speed; a bonus for a streak of right answers; the standings after each question and a podium at the end; a team mode (one score from the members' answers)
- Solution: its own milestone: a run mode led by the host with a shared question pointer pushed to the participants (HTMX polling or SSE), timing per question measured on the server, a scoring strategy that takes the answer time, and a scoreboard view per question

### TD-095 Quiz type: full pub quiz (teams, rounds, joker, closest wins) — OPEN
- Where: the pub quiz preset covers one phone per team with the team name as nickname and pages as rounds; teams, rounds and jokers have no model (`app/domain/models.py`)
- Effect: missing for the full format: teams as an entity (members, team size limit); rounds as a unit with standings after each round; a joker round chosen by the team in advance that doubles its points; a tie-breaker where the closest number wins (the Number type only has a tolerance); pace led by the quizmaster (see TD-094)
- Solution: rounds as named groups of questions in a revision with a score per round on the scoreboard; a joker as a per-attempt choice of one round; a "closest wins" tie-break policy on a Number question; teams after TD-094 or as a participant kind

### TD-096 Quiz type: course with a practice that unlocks the final test and a certificate — OPEN
- Where: the Practice and Final test presets stand alone; quizzes do not know about each other (`app/domain/models.py`, `Quiz`)
- Effect: a course cannot require a passed practice before the final test, and a passed test gives no certificate
- Solution: a link from one quiz to another with a condition (passed or finished in the same browser or for the same participant), and a certificate page or PDF with the name, quiz, date and score, issued from the official attempt

### TD-097 Quiz type: personality quiz with an outcome instead of a score — OPEN
- Where: scoring sums points (`app/plugins/scoring/strategies.py`); the result page shows a score (`app/plugins/results/`)
- Effect: a "which … are you" quiz cannot be made: answers cannot point to outcomes, and the result cannot be an outcome with its text and image
- Solution: outcomes defined on the quiz, each choice option weighted toward outcomes, a scoring strategy that picks the outcome with the highest weight, and a result view that shows the outcome instead of the score

### TD-098 Quiz type: trail with QR stations — OPEN
- Where: a run has one link and QR code (`app/api/admin_runs.py`); questions have no place or order of unlocking
- Effect: an outdoor trail (bojovka) where each station has its own QR code that opens its question cannot be made, except as one quiz per station with no common score
- Solution: stations as groups of questions with their own QR code inside one attempt, opened in any or a fixed order, with the attempt open until the last station or the deadline

### TD-099 Quiz type: poll without right answers or score — OPEN
- Where: the Choice type allows no right answer (`app/plugins/questions/choice/plugin.py:1`), but scoring, the result page and the run statistics assume a score; left out of the quiz types (2026-11-12, `docs/superpowers/specs/2026-11-12-quiz-types-design.md`)
- Effect: a poll can only be faked as a quiz where every answer is wrong or right, and its result page shows a meaningless score
- Solution: check how a question without a right answer scores and what the statistics show per option; then a poll type with no score on the result page and the answer distribution in the statistics

### TD-100 Quiz types saved by an admin from a quiz — OPEN
- Where: quiz types come only from plugins (`docs/superpowers/specs/2026-11-12-quiz-types-design.md`)
- Effect: an admin who tuned a quiz cannot reuse its settings as a type for other quizzes, other than duplicating the quiz
- Solution: "Save as type" on the quiz settings page storing the quiz's overrides under a name, listed with the plugin types, with rename and delete

### TD-101 Navigation, reveal, shuffle and sources are read live by an open run — OPEN
- Where: `app/domain/attempts.py:234` (`settings.flow(run.quiz)` at each attempt start), `app/api/rendering.py:237` (`show_sources`), `app/domain/rewards.py:211` (reveal checked against the live quiz)
- Effect: unlike the time limit, participants, data profile, scoreboard and rewards, which a run copies when it is planned or opened, these values follow the quiz: a settings change or a new quiz type during an open run changes new attempts of that run, and sources also change on result pages of finished attempts. The quiz types overview only warns about it (`docs/superpowers/specs/2026-11-12-quiz-types-design.md`)
- Solution: copy them onto the run at planning or opening like the other run values, with a migration, and read them from the run

### TD-102 Review fixes 2026-11-16: deferred minors — OPEN
- Where: `app/domain/rate_limit.py`, `app/api/admin_runs.py`, `app/domain/rewards.py`, `app/domain/participants.py`, `app/api/play_switch.py`, `app/api/admin_forms.py`, `app/api/assets/countdown.js`, the deploy gunicorn command, and tests under `tests/`
- Effect: minor leftovers of the 2026-11-16 final review, none changes behaviour today:
  - `rate_limit.allow` and `record` are dead code kept as a test patch target
  - no archived-quiz API test for grading approve/delete, and three identical `except QuizArchived` blocks in `admin_runs`
  - the A4 test patches `events._handlers` and `is_enabled`
  - `grant_manual` loads the full grantable list and checks outside the transaction
  - no entry-point test for a stale heartbeat
  - the 35 s grace assumes the gunicorn default `graceful_timeout` (30 s) and does not pin it
  - `find_or_create` treats every `IntegrityError` as a key race
  - test gaps: switch API `IN_PROGRESS` assert, closed-run submit message, confirm Cancel link, confirm attribute in step/page/preview modes
  - the `auto_submit` marker stays for the lifetime of the page
  - the focused question section has no accessible name
  - the `<details>` split in the first-publication test is fragile
  - D3 helper tests were written without a RED step
  - verbose re-exports in `play_switch`, and `admin_forms` re-exports private `_number_help` and `_value_choices`
- Solution: remove the dead code and the duplicate blocks, pin `--graceful-timeout 30`, narrow the `IntegrityError` handling, move the grant check inside the transaction, add the missing tests, name the focused section, and tidy the re-exports

### TD-103 Full merge of runs into one — OPEN
- Where: app/domain/results.py (shared board, `QuizRun.board_main`), app/domain/models.py `QuizRun`, `Attempt`, `Participant`; ADR-0065 deferred it, ADR-0007 forbids a run taking over results.
- Effect: Runs of one quiz can only show one shared scoreboard (ADR-0065); their attempts, participants, rewards and draws stay in each run. An admin who wants one run with everyone in it cannot get it.
- Solution: Not designed. Before any work a new ADR replacing ADR-0007 has to decide:
  - whose run rules win: data profile and retention, participant rules, access code, rewards, schedule;
  - duplicate browsers and nicknames: the same browser or nickname in two runs, and which attempt is official;
  - immutable entitlements and draw history (ADR-0053): kept, recomputed or refused when a run has them;
  - what happens to the source run: deleted, archived or left empty;
  - the source run's exports and private result links: still valid, redirected or broken.

## RESOLVED

### TD-001 Project purpose missing in README — ✅ RESOLVED (2026-11-05)
### TD-002 Installation steps missing in README — ✅ RESOLVED (2026-11-05)
### TD-003 Commands and API missing in README — ✅ RESOLVED (2026-11-05)
### TD-004 Development commands missing in README — ✅ RESOLVED (2026-11-05)
### TD-005 Security contact missing — ✅ RESOLVED (2026-11-05)
### TD-006 Makefile targets are placeholders — ✅ RESOLVED (2026-11-05)
### TD-007 CI is missing — ✅ RESOLVED (2026-11-05)

# Kvízotron flows

Each flow: when a change concerns it, the links in order, what it can refuse and how to trigger it.

## Playing

- **Applies to:** `app/api/play.py`, `app/domain/attempts.py`, `app/api/rendering.py`, `app/plugins/questions/`, `app/plugins/scoring/`, `app/plugins/quiz_flow/`
- **Links:** `/q/<slug>` → `/r/<id>/start` → `attempts.start` and a signed token (the flow and page size frozen in `settings_json`) → a page without the answer key and `flow.js` per question or per page → `/a/<id>/check` → `/a/<id>/submit` → `attempts.submit` → `grade` of the type and the weight of the strategy → result and reveal.
- **Refusals:** closed run, bad token, repeated submission, tampered score.
- **Run:** `uv run pytest tests/integration/test_vertical_slice.py tests/integration/test_banks_and_flow.py tests/api/test_play.py tests/api/test_play_flow.py tests/api/test_play_check.py tests/api/test_play_reveal.py tests/domain/test_attempts.py -q`

## Content and publishing

- **Applies to:** `app/domain/authoring.py`, `app/domain/banks.py`, `app/domain/selection.py`, `app/domain/revision_diff.py`, `app/api/admin_quizzes.py`, `app/api/admin_revisions.py`, `app/api/admin_banks.py`
- **Links:** editor → draft → change overview → publishing and an immutable revision → opening a run → drawing questions at start.
- **Refusals:** missing translation, unmet module requirements, quiz changed after the overview was shown.
- **Run:** `uv run pytest tests/api/test_question_editor.py tests/api/test_admin_quizzes.py tests/api/test_admin_revisions.py tests/api/test_admin_banks.py tests/domain/test_authoring.py tests/domain/test_publish_and_open.py tests/domain/test_revision_diff.py tests/domain/test_selection.py -q`

## New revision during a run

- **Applies to:** `app/domain/attempts.py`, `app/domain/authoring.py`, `app/api/play.py`, `app/api/jinja2/public/_questions.html`
- **Links:** publishing while a run is running → choice of policy → `/a/<id>/revision-status` → notice on the page → `/a/<id>/switch` → carried-over answers and the original start.
- **Refusals:** an old submission after the switch, double click, switching after the time.
- **Run:** `uv run pytest tests/integration/test_revision_switch.py tests/api/test_switch.py tests/domain/test_switch.py tests/domain/test_run_revisions.py -q`

## Schedule and time

- **Applies to:** `app/domain/run_schedule.py`, `app/api/run_clock.py`, `app/domain/clock.py`, `app/api/admin_runs.py`, `app/api/assets/countdown.js`, `app/api/assets/planned.js`, `app/api/assets/clock.js`
- **Links:** `/admin/quizzes/<id>/plan` → `run_schedule.plan` → first request after the deadline and `settle` → open run → start with a limit → countdown and `/a/<id>/time` → automatic submission (`countdown.js` repeats it with the same key after a connection error, 5xx and 429, `start` never) → receipt time at `submit` → closing and the count of unsubmitted → archive.
- **Refusals:** start before the deadline, submission after the limit, late photo, unmet requirements at opening.
- **Run:** `uv run pytest tests/api/test_countdown_script.py tests/api/test_run_plan.py tests/api/test_planned_quiz.py tests/api/test_run_deadline.py tests/api/test_countdown.py tests/api/test_run_archive.py tests/domain/test_run_schedule.py tests/domain/test_attempt_time.py tests/domain/test_clock.py -q`
- **Outside tests:** `tools/load_deadline.py` when the submission path changes, a real submission in the browser through `kvizotron-browser-walkthrough`.

## Participants and access code

- **Applies to:** `app/plugins/participants/`, `app/domain/participants.py`, `app/domain/access_codes.py`, `app/api/rate_limit.py`, `app/api/play.py`, `app/api/public.py`, `app/api/admin_runs.py`, `app/api/jinja2/public/_identity_fields.html`
- **Links:** quiz rules → copy to the run at planning or opening → code at `/r/<id>/code` and an unlock cookie → `/r/<id>/start`: code gate, name before start, participant cookie and `participants.begin` (new, continues, replaces, refuses) → `/a/<id>/submit`: repetition and name check in one transaction → result with completion through `/v/<token>/identity` → attempts table on the run.
- **Refusals:** missing or changed code, the eleventh wrong code in a minute, already played, time expired, abandoned attempt, name taken, missing required name or e-mail.
- **Run:** `uv run pytest tests/contracts/test_participants.py tests/domain/test_participant_rules.py tests/domain/test_repetition.py tests/domain/test_identity.py tests/domain/test_access_codes.py tests/api/test_participant_cookie.py tests/api/test_identity_flow.py tests/api/test_access_code_flow.py tests/api/test_run_attempts_table.py tests/integration/test_no_personal_data_in_logs.py -q`
- **Outside tests:** `make smoke` for the IP behind Caddy, a browser walkthrough for the name error in step mode.

## Photos and grading

- **Applies to:** `app/plugins/questions/image_answer/`, `app/providers/media_local/`, `app/domain/grading.py`, `app/domain/visibility.py`, `app/domain/walkthrough.py`, `app/api/admin_grading.py`, `app/api/public.py`
- **Links:** multipart submission → check and rebuild of the photo → private storage → attempt waits for grading → `/admin/quizzes/<id>/grading` → grade → private link `/v/<token>` → public walkthrough.
- **Refusals:** disguised file, run limit, late photo, foreign token, photo without approval.
- **Run:** `uv run pytest tests/api/test_image_answer.py tests/api/test_image_check.py tests/api/test_grading.py tests/api/test_stored_answers.py tests/api/test_result_link.py tests/api/test_walkthrough.py tests/providers/test_media_participant.py tests/domain/test_grading.py tests/domain/test_visibility.py -q`

## Data profile and resuming

- **Applies to:** `app/domain/data_policy.py`, `app/domain/attempts.py`, `app/domain/run_schedule.py`, `app/api/play.py`, `app/api/admin_runs.py`, `app/api/assets/resume.js`, `app/plugins/quiz_flow/manifest.py`
- **Links:** profile in settings → run schedule and copy to the run → start → submission (stored, or deleted and counted) → result page. And a copy in the browser → `POST /r/<run>/resume` → submission → copy deleted.
- **Refusals:** `none` with an excluding setting, a second submission without an attempt (410), a token of a foreign or ended attempt, resuming switched off.
- **Run:** `uv run pytest tests/domain/test_data_policy.py tests/domain/test_profile_storage.py tests/domain/test_stateless.py tests/domain/test_local_resume.py tests/domain/test_migration_0013.py tests/api/test_stateless_flow.py tests/api/test_local_resume.py tests/api/test_run_plan.py -q`

## Settings

- **Applies to:** `app/domain/settings.py`, `app/domain/requirements.py`, `app/api/admin_settings.py`, `app/api/admin_forms.py`, `manifest.py` of modules
- **Links:** catalogue → fields on the scope page → saving an override → `settings.resolve` → effect on the play page and in the preview.
- **Refusals:** a choice outside the offer, conflict with another setting, a module requirement blocking publishing.
- **Run:** `uv run pytest tests/contracts/test_settings_rule.py tests/domain/test_settings.py tests/domain/test_flow_settings.py tests/domain/test_requirements.py tests/api/test_admin_settings.py tests/api/test_requirements.py -q`

## Preview and test link

- **Applies to:** `app/domain/preview.py`, `app/domain/run_links.py`, `app/api/admin_preview.py`, `app/api/admin_links.py`, `app/api/public.py`
- **Links:** preview without saving, with an optional limit → link `/t/<token>` to a chosen revision → a test run hidden from results.
- **Refusals:** submitting a preview after the limit, a cancelled or expired link.
- **Run:** `uv run pytest tests/api/test_preview.py tests/api/test_test_links.py tests/domain/test_run_links.py tests/domain/test_run_kinds.py -q`

## Import and export

- **Applies to:** `app/providers/csv_io/`, `app/domain/question_import.py`, `app/domain/question_export.py`, `app/api/admin_import.py`, `app/api/admin_export.py`, `from_csv` of question types
- **Links:** `/admin/import/new` → mapping → check → confirmation → overview → draft of a quiz or bank → export → import again unchanged.
- **Refusals:** an error in a row, a damaged or too large ZIP, an image that cannot be downloaded.
- **Run:** `uv run pytest tests/integration/test_csv_round_trip.py tests/api/test_import.py tests/domain/test_question_import.py tests/domain/test_question_export.py tests/providers/test_csv_reader.py tests/providers/test_csv_writer.py tests/contracts/test_csv_io.py -q`

## Module

- **Applies to:** `app/kernel/`, `app/contracts/`, `pyproject.toml`, `manifest.py` of modules
- **Links:** entry point → `load_modules` and dependency order → `INSTALLED_APPS` → `ready()` and the registry → editor, playing and grading.
- **Refusals:** missing dependency, incompatible version, a key registered twice, a switched-off module with an old revision.
- **Run:** `uv run pytest tests/integration/test_ac01_question_plugin.py tests/integration/test_demo_module.py tests/integration/test_installed_project.py tests/integration/test_startup_verification.py tests/integration/test_auth_switch.py -q`

## Results and leaderboard

- **Applies to:** `app/plugins/results/`, `app/domain/results.py`, `app/domain/run_stats.py`, `app/domain/participants.py` (`needs_participant`, `attempt_rows`), `app/api/scoreboard.py`, `app/api/play.py`, `app/api/public.py`, `app/api/admin_runs.py`, `app/api/jinja2/public/scoreboard.html`, `app/api/jinja2/public/_scoreboard_rows.html`
- **Links:** quiz leaderboard setting → copy to `results_json` with a `seed` at planning or opening → a visible leaderboard sets the participant cookie even when repeating is allowed → `/a/<id>/submit` and grading → `results.board`: official attempt and ranking through `result_view`, anonymisation, hiding while grading is pending, a 5 s cache → `/q/<slug>/r/<id>/scoreboard` and the `/rows` fragment every 15 s → own place on the result → administration: display, merging revisions, statistics, run comparison, sorting of attempts.
- **Refusals:** a visible leaderboard with profile `none` or with answers after every question, duration without profile `detailed`, merging with a different maximum or a single revision, a test run (404), an archive without a switch.
- **Run:** `uv run pytest tests/contracts/test_results.py tests/domain/test_results_settings.py tests/domain/test_results_board.py tests/domain/test_run_stats.py tests/api/test_results_forms.py tests/api/test_scoreboard_page.py tests/api/test_admin_scoreboard.py tests/api/test_run_stats_page.py tests/api/test_attempts_table_sort.py tests/api/test_participant_cookie.py -q`
- **Outside tests:** browser walkthrough: refreshing on a submission from another browser, projector and full screen, phone, dark mode, Ukrainian.

## Submission → reward claim

- **Applies to:** `app/plugins/rewards/`, `app/domain/rewards.py`, `app/domain/attempts.py` (`submit`), `app/domain/grading.py`, `app/domain/results.py` (`official_attempt`), `app/domain/authoring.py` and `app/domain/run_schedule.py` (`copy_rules`, `ensure_allowed`), `app/domain/participants.py` (`needs_participant`), `app/api/admin_rewards.py`, `app/api/admin_runs.py`, `app/api/play.py` (`rewards_shown`), `app/api/public.py`, `app/api/jinja2/public/_rewards.html`
- **Links:** rules in the quiz template or a previous run → `reward_source` → copy of the rules and `rewards_json` at planning or opening and `ensure_allowed` → participant cookie → `/a/<id>/submit` → `rewards.refresh` in the submission transaction: official attempt, `reward.qualifies` by `reward_thresholds` → granting, or cancelling with "no longer reached" → end of grading `refresh` again → result and `/v/<token>` with pickup instructions → the run's rewards page: handing over, cancelling with a reason, manual granting.
- **Refusals:** rules with profile `none` or with answers after every question, a draw without a required e-mail under `require_email`, a structure change on an open run, a test run, pending grading, cancelling without a reason, manual granting of a rule of another kind or run.
- **Run:** `uv run pytest tests/contracts/test_reward.py tests/plugins/test_reward_thresholds.py tests/domain/test_reward_rules.py tests/domain/test_entitlements.py tests/api/test_admin_rewards.py tests/api/test_public_rewards.py -q`
- **Outside tests:** browser walkthrough: rules in the schedule, pickup instructions in cs/en/uk, phone and dark mode.

## Closing → drawing

- **Applies to:** `app/plugins/drawings/`, `app/domain/draws.py`, `app/domain/rewards.py` (`_grant_draw`, `_cancel_draw`, `public_winners`), `app/domain/grading.py` (`waiting`), `app/domain/data_policy.py`, `app/api/admin_rewards.py` (`run_draw`, `run_draw_action`), `app/api/jinja2/admin/prize_draw.html`, `app/api/scoreboard.py`
- **Links:** closing the run → `/admin/runs/<id>/draw`: `draws.refusal` and a preview (count, fingerprint) → POST `draw`: a snapshot rebuilt, `drawing.select` of winners and substitutes at once, `Draw` and `DrawEntry` rows with pseudonyms, audit and `draw.completed`, winners' claims → `move_up`, `substitute`, `redraw` with a reason as new rows → publishing winners → the run's leaderboard.
- **Refusals:** run not closed, profile `none`, pending grading, a test run or a rule of another kind, nobody eligible, already drawn, missing reason, no eligible substitute, nobody left for a substitute winner.
- **Run:** `uv run pytest tests/contracts/test_drawing.py tests/plugins/test_draw_selection.py tests/domain/test_prize_draws.py tests/api/test_admin_draw.py tests/api/test_public_rewards.py -q`
- **Outside tests:** browser walkthrough: the fingerprint on a phone, moving a substitute up and publishing winners on the leaderboard.

## Settings pages

- **Applies to:** `app/api/admin_view.py`, `app/api/admin_settings.py`, `app/api/admin_quizzes.py` (`settings_page`), `app/api/admin_runs.py` (`_plan_page`), `app/api/jinja2/admin/_setting_groups.html`, `admin/_section_panel.html`, `settings.html`, `quiz_settings.html`, `run_plan.html`, `app/api/assets/sections.js`, `app/plugins/theme_default/assets/theme.css` (`.section-panel`), `_quiz_header.html`, `run.html`, `app/domain/settings.py` (`group`, `level`), module manifests
- **Links:** `group` and `level` on a setting → `group_fields` by the `kvz_admin_view` cookie and what differs from the inherited value → groups on the page and a section panel with links to anchors and the Basic / All switch (also on the run page, which hides the code and data depending on the view) (wide screen: side panel, narrow: a floating "Sections" button with `<details>`; `sections.js` only marks the current section) → switch POST `/admin/view` with `next` back to the page → POST without hidden fields → saving that takes an empty value as unchanged.
- **Refusals:** a conflict on a hidden field shows the field and the error; a foreign `next` on the switch leads to `/admin/`.
- **Run:** `uv run pytest tests/domain/test_setting_groups.py tests/api/test_admin_view.py tests/api/test_run_plan.py tests/api/test_admin_layout.py tests/api/test_admin_settings.py -q`
- **Outside tests:** browser walkthrough: both views, the schedule, "More" on a phone, the section panel on a wide screen and the floating button on a phone, keyboard.

## Branding

- **Applies to:** `app/domain/branding.py`, `app/domain/models.py` (`BrandingConfiguration`), `app/plugins/theme_default/` (`colours.py`, `layout.html`, `theme.css`), `app/api/rendering.py` (`page`), `app/api/admin_branding.py`, `app/api/admin_forms.py`, `app/api/admin_settings.py`, `app/api/admin_quizzes.py` (`settings_page`), `app/api/admin_preview.py`, `app/api/play.py`, `app/api/public.py`, `app/api/scoreboard.py`, `app/api/jinja2/public/base.html`, `app/settings.py` (`SECURE_CSP`), `app/domain/creator.py`, `app/domain/models.py` (`Quiz.created_by`), `app/kernel/models.py` (`AdminUser.email`), `app/api/admin_users.py`, `app/plugins/theme_default/views.py` and `assets/badge-*.svg`
- **Links:** the admin saves texts and a logo (`/admin/settings/branding`, `/admin/quizzes/<id>/branding`) or a palette and colours (the settings form, `require_colours`) → `branding.set_texts`, `set_logo`, `set_colours`, audit `branding.changed` without values → `branding.resolve(branding_quiz, locale)` per field quiz → global → built-in value, palette and colours from the level that chose `custom` → `theme.derive_palette` adjusts colours to WCAG AA → `rendering.page` gives the template `branding` and `csp_nonce` → theme layout: name, logo, `data-palette`, a `<style nonce>` block only for `custom` → `public/base.html`: a single footer line in the order administrator text · `GPL-3.0-or-later` · Python, Django, HTMX badges (theme) · "Runs on Kvízotron <version>" linking to the About page · the year in the configured zone · contact e-mail (`mailto:`), a missing part is left out. Contact e-mail: `branding.set_contact_email` → `resolve` quiz → global → `creator.creator_email(quiz)` from `Quiz.created_by` (new quiz, duplication, import; older ones by migration `0018`) and `AdminUser.email` from the Admins page; without a quiz nothing. Quiz pages (playing, result, leaderboard, projector, preview, test link) pass `branding_quiz`, the others take the global one.
- **Refusals:** `custom` without both colours, a colour outside `#rrggbb`, text over the limit (name 80, motto 160, footer 300), an invalid contact e-mail or administrator e-mail (over 254 characters), a rejected logo file, an archived quiz (409).
- **Run:** `uv run pytest tests/domain/test_branding.py tests/plugins/test_theme_colours.py tests/test_palettes.py tests/api/test_branding_pages.py tests/api/test_admin_branding.py tests/contracts/test_theme_default.py tests/domain/test_quiz_created_by.py tests/api/test_quiz_created_by.py tests/api/test_admin_users.py tests/kernel/test_admin_user.py -q`
- **Outside tests:** browser walkthrough: custom colours in light and dark mode without a CSP error in the console, phone, logo, preview and a test link with the quiz's colours, the footer line on a phone, Ukrainian.

## Results export

- **Applies to:** `app/contracts/__init__.py` (`ExportTable`, `ExportJobView`, `ResultsExporterProvider`, `TableSinkProvider`), `app/providers/csv_io/` (`results.py`, `writer.write_table`, `models.ExportJobRecord`, `limits.py`), `app/domain/results_export.py`, `app/domain/results.py` (`board(audience="admin")`, `official_attempt`, `BoardRow.attempt_id`), `app/domain/run_stats.py` (`of_revision`), `app/domain/clock.py` (`iso`), `app/api/admin_results_export.py`, `app/api/export_runner.py`, `app/api/jinja2/admin/results_export.html`, `_export_jobs.html`, `run.html` (Export section), `runs.html` (checkbox in the comparison), `_quiz_header.html` (Export results)
- **Links:** a run, a quiz or a run comparison → `/admin/exports/new?quiz=&runs=` → `results_export.offered` by data profile → POST with files, `bundle`, photos and confirmation of personal data → `create` (an `export_job` row `queued`, `choices_json`, `BOOT`) and audit `export.created` → `export_runner.kick()` → `claim_next()` (slots 1 per admin, 2 in the app) → thread: `results_export.tables` and `photo_files` → `write()` to `exports/<id>/` (CSV `;`, BOM, CRLF, formula protection except numbers in `numeric`, or a ZIP with photos) → `done` → the fragment `/admin/exports/jobs` every 2 s → download `/admin/exports/<id>/<file>` only for the author, audit `export.downloaded` → deletion after 24 hours at the next use of the page. A job from another process → `interrupted` → "Start again".
- **Refusals:** no file, a file the runs do not give, an invalid `bundle`, personal data without confirmation (400); a foreign, test or unknown run (404); downloading a foreign, unfinished or expired job (404); restarting a job that is neither `interrupted` nor `failed` (404); a thread that cannot be started (`failed`).
- **Run:** `uv run pytest tests/contracts/test_table_sink.py tests/contracts/test_csv_io.py tests/providers/test_csv_writer.py tests/providers/test_csv_results.py tests/domain/test_results_export.py tests/api/test_results_export.py -q`
- **Outside tests:** a real thread (tests call it synchronously), browser walkthrough: the export page on a computer and a phone, refreshing the job list, a CSV opened in LibreOffice (split columns, diacritics), a ZIP with photos.

## Deleting run data

- **Applies to:** `app/domain/retention.py`, `app/domain/data_policy.py` (`deletion_at`, `is_due`, `days_left`, `deletion_soon`), `app/domain/run_stats.py` (`freeze`, reading from the summary), `app/domain/run_schedule.py` (`settle`, `set_period`), `app/domain/results.py` and `walkthrough.py` (state `data_deleted`), `app/domain/migrations/0019_retention.py`, `app/domain/management/commands/` (`jobs.py`, `retention.py`), `app/domain/heartbeat.py` (the record of a pass, the "Last pass" line on `retention.html`), `app/domain/migrations/0020_participant_email_key.py`, `app/providers/retention/`, `app/providers/csv_io/results.py` (`delete_for_runs`), `app/providers/media_local/provider.py` (`private_assets_older_than`), `app/api/admin_retention.py`, `app/api/jinja2/admin/` (`retention.html`, `erasure.html`, `_erasure_rows.html`, `_deletion.html`, `run.html`, `runs.html`), `deploy/compose.yaml` (the `jobs` service)
- **Links:** the `jobs` service every hour `run_pass` → `run_schedule.settle` → a run past its period (`data_policy.is_due`, not held) or with a summary without `data_deleted_at` → `purge_run`: a summary with counts → attempts by 200 (`replaced_by` first, photos after the commit) → exports → the last transaction (values, claims, participants, profile `none`, `ARCHIVED`, `data_deleted_at`, a `retention_job` record, audit `run.data_deleted`, event `retention.executed`) → late exports → `sweep`. "Delete data now" (`delete_now`) goes the same way. Erasure: `/admin/retention/erasure` POST → `search_email` (one query by `Participant.email_key`, set by `participants.claim_name`) or `search_name` → ticking → confirmation → `erase` per run (`run.participants_erased`, for an e-mail its fingerprint; the summary of a deletion in progress is reduced by the deleted rows; after the commit `results.clear_board_cache`) → `/admin/retention`. The summary holds `trigger`, `admin_id` and the marker `late_exports_pending`, which `run_pass` tries by removing late exports after 24 hours. A held run → `/admin/retention/held` → `release_held` → the next pass.
- **Refusals:** deleting a run that has not ended (`not_ended`), changing the period of a deleted run (`data_deleted`), shortening the period into the past without confirmation (`PeriodNeedsConfirmation`), no ticked erasure rows, export files that cannot be removed (the deletion stops and the next pass continues), public pages of a deleted run (an unavailable state).
- **Run:** `uv run pytest tests/domain/test_retention_due.py tests/domain/test_retention_purge.py tests/domain/test_retention_pass.py tests/domain/test_retention_period.py tests/domain/test_retention_stats.py tests/domain/test_retention_erasure.py tests/domain/test_migration_0019.py tests/api/test_admin_retention.py tests/api/test_retention_public.py tests/contracts/test_retention.py tests/providers/test_export_retention.py -q`
- **Outside tests:** the real `jobs` service (`make smoke`, the `jobs` healthcheck after a minute), browser walkthrough: the Deletion history with the "Last pass" line before and after a pass, held runs, an erasure request, the deletion date on a run and in the run list in both colour modes and on a phone.

## Switching a module off

- **Applies to:** `app/kernel/lifecycle.py` (`blockers`, `set_enabled`), `app/domain/usage.py`, `app/domain/plugin_overview.py`, `app/api/admin_plugins.py`.
- **Links:** `/admin/plugins` → `/admin/plugins/{id}` → POST `/admin/plugins/{id}/state` → `lifecycle.set_enabled` → `registry.is_enabled` → editor, publishing, preview and rewards stop offering the plugin; stored content is read with `include_disabled=True`.
- **Refusals:** a provider, `always_on`, the last theme, a scheduled or open run, a live reward rule, a dependency of another module. The page answers 409 with the reasons in the admin's language.
- **Run:** `uv run pytest tests/kernel/test_lifecycle.py tests/domain/test_usage.py tests/domain/test_plugin_overview.py tests/api/test_admin_plugins.py tests/api/test_disabled_plugin.py -q`
- **Outside tests:** browser walkthrough: the module list, switching off a question type, the detail with "Different elsewhere", phone.

## Request limits

- **Applies to:** `app/api/rate_limit.py`, `app/api/play.py` (`_limited`, `start`, `submit`, `run_code`), `app/api/admin_auth.py` (`login_page`), `app/api/assets/countdown.js`, `app/settings.py` (`KVZ_*_PER_MINUTE`), `deploy/Caddyfile` (`X-Forwarded-For`, `keepalive`), `tests/api/test_request_limits.py`
- **Links:** view → `client_ip` (the first `X-Forwarded-For` value, which Caddy writes) → `rate_limit.allow(bucket, key)` as the first thing in the view (`start` and `submit` count every request; `code` only failures after the check) → `record`; login takes a slot in the buckets `login` (name and address) and `login_address` (address only) through `try_acquire` before `authenticate()` and returns them through `release` on a correct login → on exceeding, 429 with `Retry-After: 60` (a fragment for HTMX, otherwise a page; for login the form with a message).
- **Refusals:** the sixth wrong login in a minute (also a concurrent one), the 31st wrong login from one address across different names, the eleventh wrong code, the 121st submission and the 301st start from one address; a new public route with a POST without a declared bucket or reason (`test_request_limits.py`).
- **Run:** `uv run pytest tests/api/test_rate_limit.py tests/api/test_login_limit.py tests/api/test_play_limits.py tests/api/test_request_limits.py tests/api/test_access_code_flow.py tests/test_deploy_headers.py -q`
- **Outside tests:** `make load` (the address check: a LAN source is counted separately), browser walkthrough: the 429 page at login and at start (in the form's language), a forced 500 and 429 at automatic submission with a waiting message.

## Daily backup

- **Applies to:** `app/domain/backup.py`, `app/domain/management/commands/jobs.py` (`pass_once`, `keep_beating`), `app/domain/management/commands/backup.py`, `app/domain/heartbeat.py`, `app/api/heartbeat.py`, `deploy/compose.yaml` (volume `backups` only in `jobs`, the `jobs` healthcheck), `Dockerfile` (`/data/backups`), `app/settings.py` (`KVZ_BACKUP_PATH`, `KVZ_BACKUP_RETENTION_DAYS`)
- **Links:** `jobs` every hour `pass_once` → `retention.run_pass` (its own `try`) → `backup.due` (local date) → `create`: lock, `.tmp-<date>`, a database copy with the backup API, media (hard links to unchanged files), `manifest.json` → `verify` (integrity, sums, migrations) → `fsync` → rename to `YYYY-MM-DD` → `prune` after every attempt, even a failed one (the newest valid backup stays; it returns `PruneResult`, `jobs` logs a leftover directory by count and the pass stays `ok`, the `backup` command ends with an error). `pass_once` writes a pass record (`ok` or `failed`), which the `jobs` healthcheck and the Deletion history read; the `jobs` heartbeat is written by a thread every 15 s, the `app` heartbeat by `HeartbeatMiddleware` at most once per 10 s.
- **Refusals:** a database that is not a file, a copy over the time limit, a file other than in the manifest, migrations the code does not know (after switching a provider), a second backup at the same time. A failure goes to the log only by type.
- **Run:** `uv run pytest tests/domain/test_backup.py tests/domain/test_jobs_backup.py tests/domain/test_heartbeat.py tests/domain/test_jobs_heartbeat.py tests/api/test_heartbeat_middleware.py tests/test_deploy_healthcheck.py -q`
- **Outside tests:** `make smoke` (the backup at the start of `jobs`, a manual backup), `make load` (a backup during submission).

## Restore from a backup

- **Applies to:** `app/domain/backup.py` (`resolve`, `restore`, `MARKER`), `app/domain/heartbeat.py`, `app/domain/management/commands/restore.py`, `deploy/load.sh` (waiting for the heartbeat), `deploy/compose.yaml`, `docs/deployment.md` (procedure)
- **Links:** `docker compose -f deploy/compose.yaml stop caddy app jobs` → `docker compose run --rm --no-deps jobs python manage.py restore <date|latest>` → `resolve` → lock → refusal while a marker `pre-restore-*/.restoring` exists → `verify` → an older schema → a live service (a heartbeat of `app` or `jobs` younger than 60 s) → a database in use (`BEGIN EXCLUSIVE`, a leftover `-wal` or `-shm`) → a copy of the existing data to `pre-restore-<time>` → the `.restoring` marker → replacing the contents of the database and media with copies (never a link) and owner uid 1000 → checking the sums → deleting the marker; on an error the original data is returned and the marker deleted, only when all of it came back.
- **Refusals:** a damaged backup (`latest` does not fall back to an older one), an older schema, a running `app` or `jobs`, a database in use, an unfinished earlier restore (the marker), an unknown date; a failure after the data copy returns the original state. `prune` never deletes a marked directory.
- **Run:** `uv run pytest tests/domain/test_restore.py tests/domain/test_backup.py -q`
- **Outside tests:** `make smoke` (`restore latest`), `make load` (a rehearsal after live data changed; the script repeats `restore latest` at most 18 times at 5 s, only while the refusal contains "counts as stopped"), a manual restore from `pre-restore-*` and removing the marker according to `docs/deployment.md`.

## Load (`make load`)

- **Applies to:** `deploy/load.sh`, `tools/load_participants.py`, `tests/integration/test_concurrent_submissions.py`, `tests/support/file_database.py`, `tests/support/server.py`, `deploy/Caddyfile`, `app/api/rate_limit.py`, `app/domain/backup.py`, `Makefile`
- **Links:** `make load` → project `kvizotron-load` → three quizzes (`load` with a photo, `reveal`, `probe`) → a backup in `jobs` runs during the submission → 50 clients from one address: start, submitting at once with a photo, repeating → a window against backups → counts and a fingerprint from the database, without `database is locked` → a walkthrough with reveal → the address check → backup, change of live data, `restore latest`, comparison → the count of queries of a public page.
- **Refusals:** a response outside 2xx including 429, a different number of attempts or photos, a backup outside the submission window, a restore that does not bring back the original fingerprint; without a LAN address the address check is not measured.
- **Run:** `uv run pytest tests/integration/test_concurrent_submissions.py tests/test_load_participants.py tests/test_makefile.py -q`
- **Outside tests:** `make load` (Docker, minutes); the output belongs in the milestone's final report.

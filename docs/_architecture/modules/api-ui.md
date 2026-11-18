# Module: API & UI composition

Package: `app/api/` — routing composition, thin views. Server-rendered HTML (Jinja2) with HTMX
and small vanilla JavaScript without a build step for editors and specific question types
([ADR-0036](../adr/0036-django-web-framework-and-orm.md)). Visual layer comes from the active
[ThemePlugin](../plugins/theme-default.md).

## Public part and language

- `FR-01` The landing page lists active and public quizzes; one can be highlighted/pinned. No
  participant registration.
- `FR-02` Each quiz has its own stable URL and QR code. Recommended URL `/q/{slug}` opens the current
  run; `/q/{slug}/r/{run_id}` opens one specific run. Archived runs have view-only mode subject to
  permissions and retention (public links to archived results are off by default: [ADR-0031](../adr/0031-public-links-to-archived-results.md)).
- `FR-03` Participant chooses a supported language. The platform supports `cs`, `en`, `uk`; admin
  decides which are required and published for a quiz. A quiz cannot be published without complete
  translations of the *selected* languages. Results are shared across languages; texts and media
  captions are localised. See [ADR-0018](../adr/0018-locales-cs-en-uk-per-quiz-required.md).
- `FR-04` Admin UI in Czech and English; public UI supports cs/en/uk.
- `FR-50` Application settings have a global value on `/admin/settings`, and a quiz can override them on its
  edit page. A quiz override beats the global value, which beats the default. Changes are audited. Saving a
  setting never creates a draft ([ADR-0038](../adr/0038-revision-switch-policy-and-settings.md)).
- `FR-51` Every setting has a fixed place (table below). What applies to all quizzes is in `Settings`, to one
  quiz in its tabs, to one run on the `Runs` tab or on the run's tabs. A quiz can override a global value, and each page
  says when a change takes effect. The quiz header shows status next to one main button whose label and action follow
  the quiz state (`app/domain/quiz_state.py`). All actions work by keyboard and without JavaScript.
- `FR-53` Colours are a setting with five presets (`color_palette`), global with a quiz override. A quiz's public pages use
  its resolved palette; the home page, information pages and administration use the global one. Every text and background
  pair reaches WCAG AA in light and dark mode. Custom colours are a sixth choice, `custom`, with a main and an accent colour; the theme derives the palette and adjusts colours that miss AA ([ADR-0054](../adr/0054-branding-owned-by-domain-and-theme.md)).

## Where things are set

| Place | Now | Later (proposal) | Takes effect |
|---|---|---|---|
| Settings | revision switch policy, palette, `none_option`, `show_sources`, navigation mode, page size, when and what to reveal (also after the run closes), shuffling, attempt limit, pass mark, at most attempts, more attempts after passing, announcing planned quizzes, the switch for the large logo on the home and About pages (global only: those pages belong to no quiz), time zone (with a clock panel), data profile, retention period, local resume, the thirteen scoreboard settings (with `scoreboard_runs`, which runs' boards the quiz page offers, read on every load), the three reward settings (source of a new run's rewards, several thresholds, contacting winners), branding of the application (name, motto, logo, a separate larger logo for the home page, footer, public contact e-mail, and the two colours of `custom` next to the palette; `/admin/settings/branding` for the texts and logos, each logo by upload or by address) | modules | Immediately, except navigation, page size, reveal, shuffling and sources: a run copies these seven when it is planned or opened and keeps them, so a change applies from the next run ([ADR-0069](../adr/0069-run-keeps-flow-settings.md)); saving a quiz's settings or applying a quiz type asks whether the planned or open run takes the change too |
| Admins | admin accounts, each with an optional e-mail that a quiz footer can show as its contact | | Immediately |
| Banks | banks (name edited on the spot), their questions, folders (names on the spot) and tags, the languages of a bank and the language of the listed texts | | Copied at publication |
| Quiz, Questions | questions, answers, images, points, scoring, reveal count, direction, sources, explanation, draw rows | | After publication |
| Deletion history | a line with the time and outcome of the last `jobs` pass ("Last pass: …, ok", "failed" or "stopped", "No pass has finished yet", absent without a record file, [ADR-0061](../adr/0061-heartbeat-and-restore-marker.md)), held runs waiting for one confirmation, the history of every deletion, checking whether an e-mail was erased, the erasure request page ([ADR-0056](../adr/0056-retention-job-summary-held-runs.md)) | | Confirmed held runs on the next pass, an erasure immediately |
| Quiz, Runs | "Delete data now" on an ended run, the date of deletion in the list of runs and on the run's Overview (within 14 days a different colour and the days left), list of runs, QR code (from the quiz's `public_origin`, else the admin's address, ADR-0067), submitted and unsent counts (a count only, under profile `none`), plan with start, deadline, limit, the eight participant rules (with at most attempts and more attempts after passing), the pass mark, data profile, retention period and scoreboard settings, access code (set, generate, remove; a new code shown once), moving a running run's deadline, scoreboard with names and its display settings, merging revisions, statistics, comparison of runs with links to each run's statistics and scoreboard (also on the running run's panel and in the quiz header beside Preview, for the running or last run), attempts table with name, e-mail, score, time and duration (only under `detailed`) sortable by header, archive; in the plan the two reward settings of the run and a link to its rules, with a warning when a draw has no e-mail to reach winners; the run's rewards page with its rules, who holds what (handing over, cancelling with a reason, granting a manual reward); the draw page with preview, draw, move-up, substitute, redraw, history and publishing winners; a results export of one run, all runs or the runs ticked in the comparison (files, separate or as one ZIP with photos, a personal-data confirmation, the admin's jobs of the last 24 hours) | | Immediately; participant rules, pass mark, data profile, official attempt (first, best, last, average), ties, the reward settings and the rules' structure fixed once the run opens, the period, the revision mode ([ADR-0065](../adr/0065-scoreboard-by-percent-and-shared-boards.md); a change recomputes the run's entitlements, [ADR-0053](../adr/0053-rewards-tiers-alternates-and-draw-history.md) addendum 2026-11-17), the scoreboard display and the rules' texts editable on the run's tabs |
| Quiz, Revisions | history, comparison, return to an older revision | | After publication |
| Quiz, More, Rewards | the quiz's template of reward rules (kind, threshold, eligibility, winners, alternates, name, description and claim instructions per language), copied by a new run when `reward_source` is `quiz` or falls back to it | | When a run is planned or opened |
| Quiz, Settings | title, description, languages (after publication); address, highlight, the quiz type (bar above the settings), overrides of the global settings in the eight groups, anonymous label for the scoreboard in the scoreboard group, branding overrides including the contact e-mail (immediately); copy, archive | | By item |

Values that belong to the installation rather than to a quiz (domain, secret key, ports, the five request limits, the backup retention and paths) are environment variables, not settings, and are listed only in [configuration.md](../../configuration.md). A request over a limit is answered with 429 and `Retry-After: 60` ([ADR-0058](../adr/0058-rate-limit-buckets.md)); the public routes that are not limited, and why, are in [security.md](../security.md#limits-of-public-routes). D5 added no address.

Every settings page (Settings, the quiz's Settings and the run plan) lists its settings in eight groups (playing, answers and result, participants, scoreboard, rewards, data, look and listing, technical), alphabetical by their label in the admin's language. Inside a group the settings are alphabetical by their label, a dependant indented under the setting it follows; a choice of at most three values is a row of radio buttons, and the global and quiz settings have a search like the bank's ([AC-168](../acceptance-criteria.md)). A section panel on each of these pages and on each tab of a run (a sticky side panel on wide screens, a floating "Sections" button on narrow ones) links to each section of the page and holds the switch "Basic / All" (cookie `kvz_admin_view`; a run's tabs have the panel and the switch too): "Basic" hides advanced settings, the access code (unless set), the data section on a run's Settings tab, and still shows a value that differs from what it inherits or was refused. The run plan shows start, deadline and limit, and collapses each group unless it differs from the quiz. Quiz tabs are Questions, Runs, Grading, Settings and "Více" with Rewards, Test links and Revisions ([ADR-0052](../adr/0052-setting-groups-levels-and-step-default.md), the panel [ADR-0054](../adr/0054-branding-owned-by-domain-and-theme.md)).

A run's parts follow one rule ([ADR-0068](../adr/0068-run-subpages.md)): each part is a tab, a page of its own with its address after `/`; `#` only jumps inside one page. Elsewhere in the administration a page with a form may post to its own address; a POST that is not the page's own form has a verb name (`…/close`, `…/archive`) or sits below the page as `…/<part>/settings` (`…/scoreboard/settings`), and `/admin/runs/<run>/settings` is the Settings tab page (GET). A run's page is therefore a set of tabs under the quiz header and a run header with a tab bar (`app/api/run_tabs.py`): Overview `/admin/runs/{id}`, Attempts `…/attempts`, Scoreboard `…/scoreboard`, Statistics `…/statistics`, and under "More" Rewards `…/rewards`, Draw `…/draw` (only with a draw rule), Export `…/export` and Settings `…/settings` (access code and data; in "Basic" only when the run has an access code or its data can be deleted now). The tab being shown is always in the bar, a form returns to its tab, and the links Statistics and Scoreboard in the quiz header and on the Runs tab go to those tabs ([AC-184](../acceptance-criteria.md)).

A quiz type sets several quiz settings in one step ([ADR-0062](../adr/0062-quiz-type-port.md), the types in [plugins/quiz-types.md](../plugins/quiz-types.md), the rules of applying in [domain.md](domain.md#quiz-types)). The new-quiz form lists the types with a one-line description in a closed disclosure "Quiz type" with none chosen; the type is applied once the quiz exists. Above the quiz's settings a bar names the type with "Deviations: N" and offers Apply again, Change type (a choice of the other types) and Remove type; a quiz without a type gets a choice of one, and a type whose module is disabled or gone keeps its name and offers only Remove. Beside each setting that deviates from the type stands "▲ type: <value>", also in "Základní". Choosing, Apply again and Change type are GET requests that show an overview (setting, current value, new value, settings back to the global value, adjusted and skipped settings, warnings about a planned or open run and about the content); only its confirmation changes the quiz, and a refusal is that overview with the settings form's message ([AC-171](../acceptance-criteria.md)).

Every public and administration page ends with a footer of two lines: the organisation's (the admin's footer text and the contact e-mail) and the application's (licence, badges, "Runs on Kvízotron" with the version, the year). The contact e-mail falls back to the quiz creator's account e-mail ([ADR-0054](../adr/0054-branding-owned-by-domain-and-theme.md)).

`none_option` is read when questions are drawn, so a change affects new page loads only. Leaving the question editor or the quiz settings with changed fields asks the browser's standard confirmation.

## HTTP surface (proposal, not a frozen API)

Public:

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Landing page (FR-01) |
| GET | `/q/{slug}` | Current run of a quiz; its scoreboard as a full-width button and, under `scoreboard_runs` "all", the public boards of the other runs ([AC-176](../acceptance-criteria.md)) |
| GET | `/q/{slug}/r/{run_id}` | Specific run |
| POST | `/r/{run_id}/start` | Start attempt, limited to `KVZ_STARTS_PER_MINUTE` a minute per address ([ADR-0058](../adr/0058-rate-limit-buckets.md)); returns the questions with `attempt_token` and `submission_key` in hidden fields |
| POST | `/r/{run_id}/resume` | Continue an attempt a browser kept a copy of; the token is in the body, no access code is needed, and a refusal that ends the attempt carries `X-Kvz-Drop-Copy` |
| POST | `/r/{run_id}/code` | Enter a run's access code; a correct one sets the unlock cookie and returns to the quiz, ten wrong ones a minute per address are allowed (`KVZ_CODE_ATTEMPTS_PER_MINUTE`) |
| POST | `/a/{attempt_id}/submit` | Submit answers, limited to `KVZ_SUBMITS_PER_MINUTE` attempts a minute per address, repeats of a counted attempt pass free ([ADR-0058](../adr/0058-rate-limit-buckets.md)); returns the score |
| POST | `/v/{token}/identity` | Fill in a missing required name or e-mail through the private result link, until the run is archived; refusals answer 200 |
| GET | `/v/{token}/photo/{answer_id}` and `/v/{token}/photo/` | The attempt's own photo through the private result link (route `result_photo`, which has a second route without the id); the part after `photo/` is read as text and anything that is not a known id of that attempt answers 204, as a refusal does, so no 404 logs the token ([ADR-0061](../adr/0061-heartbeat-and-restore-marker.md)) |
| POST | `/a/{attempt_id}/time` | Seconds left, asked every 30 s while playing and when the tab is seen again |
| GET | `/a/{attempt_id}/revision-status` | Polled every 30 s while playing: 204 nothing to do, 200 notice with "Switch", 286 stop polling |
| POST | `/a/{attempt_id}/switch` | Move to the round's current revision and keep answers to unchanged questions (FR-47) |
| GET | `/q/{slug}/r/{run_id}/scoreboard` | Public scoreboard of a normal run (`?view=projector`, only for a signed-in admin, who alone gets the link: only the board in large type, no bar, links, buttons or footer; links to it open a new window; without a login the address shows the normal board); a hidden board says why; 404 for a test run. Published draw winners by nickname or anonymous label, also under a hidden board, on the page only (not in `/rows`) |
| GET | `/q/{slug}/r/{run_id}/scoreboard/rows` | The table as an HTMX fragment, polled every 15 s until the run has ended and nothing waits for grading |
| GET | `/media/{asset_id}` | A stored image, with safe headers |
| GET | `/how-it-works`, `/about` | Information pages |
| GET | `/privacy` | Privacy notice for the current version, with the global default retention period and the browser copy; the complete notice (FR-35) comes in Stage D |

Administration: `/admin/login`, `/admin/quizzes` (`?archived=1` lists archived quizzes), `/admin/quizzes/{id}/edit`,
`/admin/quizzes/{id}/settings`, `/admin/quizzes/{id}/runs` (GET the tab, POST opens a run), `/admin/quizzes/{id}/publish` (`?start=1` publishes and opens a run together, `?then=plan` publishes and goes on to the run plan), `/admin/quizzes/{id}/revisions`,
`/admin/quizzes/{id}/revisions/{no}/compare`, `/admin/quizzes/{id}/revisions/{no}/restore`,
`/admin/quizzes/{id}/draft/discard`, `/admin/quizzes/{id}/duplicate`, `/admin/quizzes/{id}/archive`,
`/admin/quizzes/{id}/restore`, `/admin/quizzes/{id}/type` (route `admin_quiz_type`: GET `?type=` or POST without `confirm=1` shows the overview, POST with `confirm=1` applies; a refusal 409, an unknown or disabled type 404), `/admin/quizzes/{id}/type/remove` (POST), `/admin/runs/{id}` and its tabs `…/attempts`, `…/scoreboard`, `…/statistics`, `…/export`, `…/settings` (GET), `/admin/runs/{id}/code` (set, generate or remove the access code), `/admin/runs/{id}/period` (route `admin_run_period`, change the retention period), `/admin/runs/{id}/scoreboard/settings` (POST the display settings), `/admin/runs/{id}/close` (GET asks, POST ends the run), `/admin/runs/{id}/results`,
`/admin/plugins` lists modules and `/admin/plugins/{module id}` shows one with its settings; a POST to `/admin/plugins/{module id}/state` with `enabled=on|off` switches a plugin ([ADR-0057](../adr/0057-plugin-admin-reasons-locks-no-configuration-table.md)).

`/admin/quizzes/{id}/rewards` (the quiz's template on the tab More, Rewards), `/admin/quizzes/{id}/rewards/new`, `/admin/runs/{id}/rewards` (the run's rules and entitlements), `/admin/runs/{id}/rewards/new`, `/admin/runs/{id}/rewards/grant` (POST a manual reward for one participant), `/admin/rewards/{rule_id}` (POST saves a rule, only its texts once the run is open, or deletes it with `action=delete`), `/admin/entitlements/{id}` (POST `action=hand_over`, or `cancel` with a `reason`), `/admin/runs/{id}/draw` (GET shows each draw rule's refusal or eligible preview, winners, alternates and history, and never draws), `/admin/runs/{id}/draw/{rule_id}` (POST `action` = `draw`, `redraw`, `move_up`, `substitute`, `publish` or `unpublish`; move-up and substitute name the winner's `entry`, every repeat needs a `reason`; a refusal answers 409, a missing reason 400), `/admin/retention` (route `retention_history`: Deletion history, held runs above it, newest first, 200 rows a page with `?page=`, one run's rows with `?run=`), `/admin/retention/held` (POST asks, with `confirm=1` releases every held run for the next pass), `/admin/retention/erasure` (search by e-mail or nickname in a POST body, tick rows, confirm; a response that can show an address is not cached), `/admin/retention/verify` (POST an address: whether and when it was erased, and by whom), `/admin/runs/{id}/delete-data` (POST asks, with `confirm=1` deletes the run's data; refused before the run has ended), `/admin/plugins`, `/admin/settings`, `/admin/import`, `/admin/export` (questions),
`/admin/exports/new?quiz={id}&runs={id,…}` (results export of a quiz's runs, all of them without `runs`; GET the page, POST starts a job with the chosen `files`, `bundle` = `separate` or `zip`, `photos` and, for personal data, `personal_ok`; a refusal answers 400 and keeps the choices; a foreign, test or unknown run 404), `/admin/exports/jobs` (the admin's job list as an HTMX fragment, polled every 2 s while a job waits or runs), `/admin/exports/{job}/restart` (POST, only an interrupted or failed job, else 404), `/admin/exports/{job}/{name}` (the file as an attachment with `private, no-store`, only for the admin who created the job while it is done and unexpired, else 404) ([ADR-0055](../adr/0055-results-export-background-job-and-csv-dialect.md)). The export page is reached from the run's Export tab, the quiz header (Export results, once the quiz has a run) and the runs comparison (checkboxes, Export selected).

Start, submit and switch return HTML: a fragment for an HTMX request (`HX-Request`), otherwise a whole page, so
playing also works without JavaScript. They are `csrf_exempt` because they have no session; the signed
token protects them. Errors have their own status and a translated message; for HTMX they carry
`HX-Retarget: #play-message`, so the answers stay on screen; a refused name or e-mail goes to `#identity-error` instead. There are no JSON endpoints yet.

Participant refusals ([ADR-0049](../adr/0049-participants-and-access-code.md)): `already_played` 409, `time_is_up` 410, `attempt_closed` 409, `attempt_gone` 410 (a stateless attempt already submitted or ended), `code_required` 403, `name_taken` 409, a missing or invalid name or e-mail 422.

Question inputs are named `<question id>:<field>`, which is how the server assembles each answer.

Languages: `?lang=` or the form's `lang`, then `Accept-Language`, each limited to what the quiz
publishes, then its default. The admin's choice is kept in the session. Texts are Django gettext
catalogues per app and plugin; source strings are English, and `make messages` extracts and compiles them.

## Editor MUST allow

- create a question via its question-type plugin;
- translations per language;
- set scoring and ordering;
- assign questions from a bank;
- preview;
- validate missing information;
- publish a new revision;
- create a new run;
- choose test variant (preview / test mode);
- manage results.

## Cross-cutting UI rules

- Views are thin: validation and business rules live in domain services and modules.
- Every state-changing admin request is CSRF-protected and authorised on the backend ([../security.md](../security.md)).
- Public pages receive only `public_payload()` data — never answer keys.
- A name that the administration lets one change on the spot is shown with a pencil (AC-160): the name of a bank, a folder (in its row and as the heading of the folder one is inside), a quiz (the default language only; a change makes a draft and the page says visitors see it after publication), a reward (the default language, beside the summary of its row, text only so it works on a running run) and the nickname of a participant in the table of attempts of a run (AC-161). One component draws them (`admin/_inline_name.html`, `app/api/inline_name.py`, `assets/inline-edit.js`): with HTMX the pencil swaps the display and the field as partials, without JavaScript it is a link to the same page with `?edit=` and a refusal is that page with status 400. A refusal keeps what was typed; the last save wins. Names of banks and folders have one value for all languages; the bank page lists the languages its questions are complete in and sets the language of the listed texts (AC-162).

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
- `FR-51` Every setting has a fixed place (table below). What applies to all quizzes is in `Nastavení`, to one
  quiz in its tabs, to one run on the `Běhy` tab or the run page. A quiz can override a global value, and each page
  says when a change takes effect. The quiz header shows status next to one main button whose label and action follow
  the quiz state (`app/domain/quiz_state.py`). All actions work by keyboard and without JavaScript.
- `FR-53` Colours are a setting with five presets (`color_palette`), global with a quiz override. A quiz's public pages use
  its resolved palette; the home page, information pages and administration use the global one. Every text and background
  pair reaches WCAG AA in light and dark mode. Custom colours come with branding in D1.

## Where things are set

| Place | Now | Later (proposal) | Takes effect |
|---|---|---|---|
| Nastavení | revision switch policy, palette, `none_option`, `show_sources`, navigation mode, when and what to reveal, shuffling, attempt limit, announcing planned quizzes, time zone (with a clock panel), data profile, retention period, local resume, the twelve scoreboard settings, the three reward settings (source of a new run's rewards, several thresholds, contacting winners) | branding, modules | Immediately |
| Správci | admin accounts | | Immediately |
| Banky | banks, their questions and tags | | Copied at publication |
| Quiz, Otázky | questions, answers, images, points, scoring, reveal count, direction, sources, explanation, draw rows | | After publication |
| Quiz, Běhy | list of runs, QR code, submitted and unsent counts (a count only, under profile `none`), plan with start, deadline, limit, the six participant rules, data profile, retention period and scoreboard settings, access code (set, generate, remove; a new code shown once), moving a running run's deadline, scoreboard with names and its display settings, merging revisions, statistics, comparison of runs with links to each run's statistics and scoreboard (also on the running run's panel and in the quiz header beside Preview, for the running or last run), attempts table with name, e-mail, score, time and duration (only under `detailed`) sortable by header, archive; in the plan the two reward settings of the run and a link to its rules, with a warning when a draw has no e-mail to reach winners; the run's rewards page with its rules, who holds what (handing over, cancelling with a reason, granting a manual reward); the draw page with preview, draw, move-up, substitute, redraw, history and publishing winners | | Immediately; participant rules, data profile, official attempt, ties, revision mode, the reward settings and the rules' structure fixed once the run opens, the period, the scoreboard display and the rules' texts editable on the run page |
| Quiz, Revize | history, comparison, return to an older revision | | After publication |
| Quiz, Více, Odměny | the quiz's template of reward rules (kind, threshold, eligibility, winners, alternates, name, description and claim instructions per language), copied by a new run when `reward_source` is `quiz` or falls back to it | | When a run is planned or opened |
| Quiz, Nastavení | title, description, languages (after publication); address, highlight, overrides of the global settings in the seven groups, anonymous label for the scoreboard in the scoreboard group (immediately); copy, archive | | By item |

Every settings page (Nastavení, the quiz's Nastavení and the run plan) lists its settings in seven groups in one order: playing, answers and result, participants, scoreboard, data, look and listing, technical. The admin bar has a switch "Základní / Vše" (cookie `kvz_admin_view`): "Základní" hides advanced settings, the access code (unless set), the data section and merging on a run page, and still shows a value that differs from what it inherits or was refused. The run plan shows start, deadline and limit, and collapses each group unless it differs from the quiz. Quiz tabs are Otázky, Běhy, Hodnocení, Nastavení and "Více" with Odměny, Testovací odkazy and Revize ([ADR-0052](../adr/0052-setting-groups-levels-and-step-default.md)).

`none_option` is read when questions are drawn, so a change affects new page loads only. Leaving the question editor or the quiz settings with changed fields asks the browser's standard confirmation.

## HTTP surface (proposal, not a frozen API)

Public:

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Landing page (FR-01) |
| GET | `/q/{slug}` | Current run of a quiz |
| GET | `/q/{slug}/r/{run_id}` | Specific run |
| POST | `/r/{run_id}/start` | Start attempt; returns the questions with `attempt_token` and `submission_key` in hidden fields |
| POST | `/r/{run_id}/resume` | Continue an attempt a browser kept a copy of; the token is in the body, no access code is needed, and a refusal that ends the attempt carries `X-Kvz-Drop-Copy` |
| POST | `/r/{run_id}/code` | Enter a run's access code; a correct one sets the unlock cookie and returns to the quiz, ten wrong ones a minute per IP are allowed |
| POST | `/a/{attempt_id}/submit` | Submit answers; returns the score |
| POST | `/v/{token}/identity` | Fill in a missing required name or e-mail through the private result link, until the run is archived; refusals answer 200 |
| POST | `/a/{attempt_id}/time` | Seconds left, asked every 30 s while playing and when the tab is seen again |
| GET | `/a/{attempt_id}/revision-status` | Polled every 30 s while playing: 204 nothing to do, 200 notice with "Switch", 286 stop polling |
| POST | `/a/{attempt_id}/switch` | Move to the round's current revision and keep answers to unchanged questions (FR-47) |
| GET | `/q/{slug}/r/{run_id}/scoreboard` | Public scoreboard of a normal run (`?view=projector` large type); a hidden board says why; 404 for a test run. Published draw winners by nickname or anonymous label, also under a hidden board, on the page only (not in `/rows`) |
| GET | `/q/{slug}/r/{run_id}/scoreboard/rows` | The table as an HTMX fragment, polled every 15 s until the run has ended and nothing waits for grading |
| GET | `/media/{asset_id}` | A stored image, with safe headers |
| GET | `/how-it-works`, `/about` | Information pages |
| GET | `/privacy` | Privacy notice for the current version, with the global default retention period and the browser copy; the complete notice (FR-35) comes in Stage D |

Administration: `/admin/login`, `/admin/quizzes` (`?archived=1` lists archived quizzes), `/admin/quizzes/{id}/edit`,
`/admin/quizzes/{id}/settings`, `/admin/quizzes/{id}/runs` (GET the tab, POST opens a run), `/admin/quizzes/{id}/publish` (`?start=1` publishes and opens a run together), `/admin/quizzes/{id}/revisions`,
`/admin/quizzes/{id}/revisions/{no}/compare`, `/admin/quizzes/{id}/revisions/{no}/restore`,
`/admin/quizzes/{id}/draft/discard`, `/admin/quizzes/{id}/duplicate`, `/admin/quizzes/{id}/archive`,
`/admin/quizzes/{id}/restore`, `/admin/runs/{id}`, `/admin/runs/{id}/code` (set, generate or remove the access code), `/admin/runs/{id}/period` (route `admin_run_period`, change the retention period), `/admin/runs/{id}/scoreboard` (POST the display settings), `/admin/runs/{id}/merge` (GET the differences, POST merges), `/admin/runs/{id}/unmerge`, `/admin/runs/{id}/close` (GET asks, POST ends the run), `/admin/runs/{id}/results`,
`/admin/quizzes/{id}/rewards` (the quiz's template on the tab Více, Odměny), `/admin/quizzes/{id}/rewards/new`, `/admin/runs/{id}/rewards` (the run's rules and entitlements), `/admin/runs/{id}/rewards/new`, `/admin/runs/{id}/rewards/grant` (POST a manual reward for one participant), `/admin/rewards/{rule_id}` (POST saves a rule, only its texts once the run is open, or deletes it with `action=delete`), `/admin/entitlements/{id}` (POST `action=hand_over`, or `cancel` with a `reason`), `/admin/runs/{id}/draw` (GET shows each draw rule's refusal or eligible preview, winners, alternates and history, and never draws), `/admin/runs/{id}/draw/{rule_id}` (POST `action` = `draw`, `redraw`, `move_up`, `substitute`, `publish` or `unpublish`; move-up and substitute name the winner's `entry`, every repeat needs a `reason`; a refusal answers 409, a missing reason 400), `/admin/plugins`, `/admin/settings`, `/admin/import`, `/admin/export`.

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

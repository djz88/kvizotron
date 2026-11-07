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
| Nastavení | revision switch policy, palette, `none_option`, `show_sources`, navigation mode, when and what to reveal, shuffling | branding, data retention, modules | Immediately |
| Správci | admin accounts | | Immediately |
| Banky | banks, their questions and tags | | Copied at publication |
| Quiz, Otázky | questions, answers, images, points, scoring, reveal count, direction, sources, explanation, draw rows | | After publication |
| Quiz, Běhy | list of runs, QR code, submitted count | schedule, time limit, access code, repetition, scoreboard, rewards, draw | Immediately |
| Quiz, Revize | history, comparison, return to an older revision | | After publication |
| Quiz, Nastavení | title, description, languages (after publication); address, highlight, overrides of the global settings (immediately); copy, archive | | By item |

`none_option` is read when questions are drawn, so a change affects new page loads only. Leaving the question editor or the quiz settings with changed fields asks the browser's standard confirmation.

## HTTP surface (proposal, not a frozen API)

Public:

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Landing page (FR-01) |
| GET | `/q/{slug}` | Current run of a quiz |
| GET | `/q/{slug}/r/{run_id}` | Specific run |
| POST | `/r/{run_id}/start` | Start attempt; returns the questions with `attempt_token` and `submission_key` in hidden fields |
| POST | `/a/{attempt_id}/submit` | Submit answers; returns the score |
| GET | `/a/{attempt_id}/revision-status` | Polled every 30 s while playing: 204 nothing to do, 200 notice with "Switch", 286 stop polling |
| POST | `/a/{attempt_id}/switch` | Move to the round's current revision and keep answers to unchanged questions (FR-47) |
| GET | `/api/runs/{id}/scoreboard` | Public scoreboard per policy |
| GET | `/media/{asset_id}` | A stored image, with safe headers |
| GET | `/how-it-works`, `/about` | Information pages |
| GET | `/privacy` | Privacy notice for the current version; the complete notice (FR-35) comes in Stage D |

Administration: `/admin/login`, `/admin/quizzes` (`?archived=1` lists archived quizzes), `/admin/quizzes/{id}/edit`,
`/admin/quizzes/{id}/settings`, `/admin/quizzes/{id}/runs` (GET the tab, POST opens a run), `/admin/quizzes/{id}/publish` (`?start=1` publishes and opens a run together), `/admin/quizzes/{id}/revisions`,
`/admin/quizzes/{id}/revisions/{no}/compare`, `/admin/quizzes/{id}/revisions/{no}/restore`,
`/admin/quizzes/{id}/draft/discard`, `/admin/quizzes/{id}/duplicate`, `/admin/quizzes/{id}/archive`,
`/admin/quizzes/{id}/restore`, `/admin/runs/{id}`, `/admin/runs/{id}/close` (GET asks, POST ends the run), `/admin/runs/{id}/results`,
`/admin/runs/{id}/draw`, `/admin/plugins`, `/admin/settings`, `/admin/import`, `/admin/export`.

Start, submit and switch return HTML: a fragment for an HTMX request (`HX-Request`), otherwise a whole page, so
playing also works without JavaScript. They are `csrf_exempt` because they have no session; the signed
token protects them. Errors have their own status and a translated message; for HTMX they carry
`HX-Retarget: #play-message`, so the answers stay on screen. There are no JSON endpoints yet.

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

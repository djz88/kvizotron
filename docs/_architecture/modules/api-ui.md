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

## HTTP surface (proposal, not a frozen API)

Public:

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Landing page (FR-01) |
| GET | `/q/{slug}` | Current run of a quiz |
| GET | `/q/{slug}/r/{run_id}` | Specific run |
| POST | `/r/{run_id}/start` | Start attempt; returns the questions with `attempt_token` and `submission_key` in hidden fields |
| POST | `/a/{attempt_id}/submit` | Submit answers; returns the score |
| GET | `/api/runs/{id}/scoreboard` | Public scoreboard per policy |
| GET | `/privacy` | Privacy notice |

Administration: `/admin/login`, `/admin/quizzes`, `/admin/quizzes/{id}/edit`,
`/admin/quizzes/{id}/revisions`, `/admin/runs/{id}`, `/admin/runs/{id}/results`,
`/admin/runs/{id}/draw`, `/admin/plugins`, `/admin/settings`, `/admin/import`, `/admin/export`.

Start and submit return HTML: a fragment for an HTMX request (`HX-Request`), otherwise a whole page, so
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

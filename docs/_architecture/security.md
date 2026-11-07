# Security

Approach: **proportionate** security for a small self-hosted application. Privacy-specific rules
live in [../privacy.md](../privacy.md).

## Requirements

- `FR-06` Optional access code per run. Only a secure hash of the code is stored; repeated attempts
  to guess the code are rate-limited.

## Controls

| Area | Control |
|---|---|
| Transport & cookies | HTTPS only; cookies `Secure`, `HttpOnly`, `SameSite=Lax`; admin session expires after 12 hours ([providers/auth-local.md](providers/auth-local.md)) |
| Passwords | Django's Argon2 hasher: Argon2id only, never plaintext or a fast hash ([ADR-0014](adr/0014-local-admin-auth-argon2id-equal-roles.md)). At least 10 characters and not on Django's common-password list |
| Admin requests | Django CSRF protection on every admin route (tested for each route and form); backend authorisation checks |
| Public play routes | `start`, `submit` and `switch` have no session, so they are `csrf_exempt` and no other route is (tested); submit and switch require the signed token, and start only creates an unscored attempt |
| Request size | Caddy refuses bodies over 16 MB, or 101 MB on an import and on a public submit, which carries all photos of an attempt; multipart is refused everywhere except the question editor for a logged-in admin, and a public submit of an attempt holding a photo question, checked before the body is read |
| Abuse | Login attempt limiting, submit rate limit, access-code attempt limiting ([ADR-0030](adr/0030-rate-limit-thresholds.md)) |
| Browser | Simple Content Security Policy; images may load from `https:`, for quizzes that load them from their server ([ADR-0043](adr/0043-external-images.md)) |
| Fetching addresses | HTTPS only, internal addresses refused unless a global switch allows them, each redirect checked again, connection to the checked address. Any admin can turn the switch on ([ADR-0043](adr/0043-external-images.md)) |
| Result integrity | Server never accepts client-computed score, correct solution or completion time as truth; signed attempt tokens ([ADR-0024](adr/0024-attempt-token-signing.md)); idempotent submission ([ADR-0009](adr/0009-server-authoritative-scoring-signed-token-idempotent-submit.md)) |
| Uploads | Admin: basic check for SVG and GIF, raster rebuilt and shrunk; every stored file is served with `nosniff` and `Content-Security-Policy: sandbox`. Participant: raster only, rebuilt from pixels, shrunk, with a per-run total limit ([ADR-0028](adr/0028-upload-limits.md)) |
| XSS | Jinja2 autoescape on all pages. Plugin output is marked safe, so the shared contract suite tests that each question type escapes admin-entered text ([ADR-0039](adr/0039-installed-modules-are-trusted-code.md)) |
| CSV | Escaping and formula-injection protection on export; a ZIP is never unpacked to disk, its names are only compared with cells, and its limits hold whatever it declares ([ADR-0045](adr/0045-csv-one-file-and-failed-images.md)) |
| Participant photos | Private assets: `/media/<id>` answers 404, served only through routes that check the right, `Cache-Control: private, no-store`. A form field cannot name an asset. Rate limits on upload wait for D5 ([ADR-0047](adr/0047-image-answer-photo-visibility.md)) |
| Result link and walkthrough | The private link is a signed reference to one attempt, no indexing, no referrer, absent from logs through status 200 and 204. The walkthrough exists only after a normal run ended, and names no participant ([ADR-0046](adr/0046-stored-answers-and-who-sees-them.md)) |
| Test links | Anyone with the address sees the questions and plays without an account, in a run that counts for nothing. Random 32 bytes, kept readable so the admin can copy it again, absent from logs and audit, no indexing, no referrer ([ADR-0044](adr/0044-preview-and-test-links.md)) |
| Data exposure | E-mail never public, never sent to external analytics; only allowed scoreboard columns public |
| Logs | No answers or PII in operational logs |
| Secrets | Configuration via environment and secrets; nothing secret in repo ([../deployment.md](../deployment.md)) |

## Audit

Audited admin operations (`audit_event`): revision publication, rule changes, plugin toggling, draws,
manual deletion, manual grading, merging scoreboard revisions, export of personal data, admin password reset. Audit records minimise PII (FR-39).

## Tamper scenarios ([AC-08](acceptance-criteria.md))

Altered `score`, `started_at`, `revision_id` or manifest in the client payload either do not affect
the result or cause rejection: these values are taken from the signed token and server state, and
the manifest hash in the token must match.

## Accepted scanner findings

Scanners report these patterns. Each was checked and is correct as written; change this table if the reason stops being true.

| Finding | Where | Why it stands |
|---|---|---|
| `django-no-csrf-token` | Jinja2 templates | The rule looks for the Django tag; these templates use `{{ csrf_input }}`, tested per form |
| `no-csrf-exempt` | `app/api/play.py` | See "Public play routes" above |
| `explicit-unescape-with-markup`, `S704` | `rendering.py`, `admin_quizzes.py` | Plugin output, escaped by the plugin and tested by the contract suite |
| `missing-autoescape-disabled`, `S701`, `direct-use-of-jinja2` | `app/api/jinja.py` | Django's Jinja2 backend sets `autoescape=True` in the options passed there |
| `direct-use-of-httpresponse` | `app/api/play.py` | The body is the output of an autoescaped template |
| `var-in-script-tag` | `theme_default/layout.html` | The `src` of a script, built with `reverse()` from a fixed list of assets |
| `non-literal-import` | `app/kernel/discovery.py` | [ADR-0039](adr/0039-installed-modules-are-trusted-code.md) |
| `unvalidated-password` | `AdminUserManager.create_admin`, `reset_admin_password` | Passwords are validated by the callers, `AdminUserForm` and `read_password`, and tested |
| `no-null-string-field` | `AuditEvent.actor_id` | `NULL` means that no user acted (a CLI command or the system), unlike any string |
| `BLE001` | `app/kernel/events.py` | The operation is already committed, so a handler must not fail it; the error type is logged |
| `B018` | `app/kernel/lifecycle.py` | Reading the attribute loads the routes at startup, which is the check |
| `E402` | `app/wsgi.py` | Models can be imported only after Django is set up |
| `F821` | Annotations in `models.py` | Python 3.15 evaluates annotations lazily; `target-version` is `py315` |
| All findings | `app/api/assets/htmx.min.js` | Vendored unchanged ([THIRD_PARTY.md](../../THIRD_PARTY.md)); `eval` is off through `allowEval: false`, tested |
| `S105`, `S106`, `S603`, hard-coded passwords, `is-function-without-parentheses`, subprocess | `tests/` | Test values and test helpers; `is_authenticated` and `is_active` are Django attributes |

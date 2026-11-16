# Security

Approach: **proportionate** security for a small self-hosted application. Privacy-specific rules
live in [../privacy.md](../privacy.md).

## Requirements

- `FR-06` Optional access code per run. Only a secure hash of the code is stored; repeated attempts
  to guess the code are rate-limited.

## Controls

| Area | Control |
|---|---|
| Transport & cookies | HTTPS only; cookies `Secure`, `HttpOnly`, `SameSite=Lax`; admin session expires after 12 hours ([providers/auth-local.md](providers/auth-local.md)); blocking or deleting an account and a new password end all its sessions at once, and the hourly `jobs` pass deletes expired sessions (AC-169) |
| Passwords | Django's Argon2 hasher: Argon2id only, never plaintext or a fast hash ([ADR-0014](adr/0014-local-admin-auth-argon2id-equal-roles.md)). At least 10 characters and not on Django's common-password list |
| Admin requests | Django CSRF protection on every admin route (tested for each route and form); backend authorisation checks |
| Public play routes | `start`, `resume`, `submit`, `check`, `attempt_time` and `switch` have no session, so they are `csrf_exempt` and no other route is (tested); all but `start` require the signed attempt token, and `start` only creates an unscored attempt |
| Request size | Caddy refuses bodies over 16 MB, or 101 MB on an import and on a public submit, which carries all photos of an attempt; multipart is refused everywhere except the question editor for a logged-in admin, and a public submit of an attempt holding a photo question, checked before the body is read |
| Abuse | Five limits per client address in process memory: failed logins (5 a minute per name and address, 30 across all names of one address), failed access codes (10), submissions (120) and starts (300); a refusal is 429 with `Retry-After`. At the defaults 50 people behind one address are not refused, with each participant sending once; repeats of the automatic submission after a failure can add sends ([ADR-0030](adr/0030-rate-limit-thresholds.md), [ADR-0058](adr/0058-rate-limit-buckets.md), [ADR-0060](adr/0060-login-reservation-and-address-ceiling.md), [TD-091](TECH_DEBT.md)) |
| Response headers | Every response carries `X-Content-Type-Options: nosniff`, a `Referrer-Policy`, a Content Security Policy and frame protection (`frame-ancestors 'none'` in the CSP, also on media); pages with private data are `no-store` with `no-referrer`. Caddy adds `Strict-Transport-Security: max-age=15552000`, without subdomains and preload ([deployment.md](../deployment.md#hsts)). Tested for each kind of response and for Caddyfile. The public scoreboard page and its rows also answer `Vary: Accept-Language, Cookie`, because the language and the "you" mark depend on both, so a shared cache would key on them ([ADR-0060](adr/0060-login-reservation-and-address-ceiling.md)). Scripts and stylesheets are cached for an hour and addressed with a fingerprint of their content (`?v=`), so a deploy reaches browsers at once and the scoreboard page or the projector link of an admin is never paired with a stale stylesheet |
| Backups | A daily backup is verified before it is published, kept for `KVZ_BACKUP_RETENTION_DAYS` days at most (the newest valid one always), and lies in a volume that only `jobs` mounts. A restore refuses a damaged or older backup, a live `app` or `jobs` (a heartbeat file younger than 60 seconds), a database that is open at that moment and an earlier restore that did not finish (a marker in `pre-restore-<time>`, which `prune` never deletes), and keeps what it replaces ([ADR-0059](adr/0059-backup-and-restore.md), [ADR-0061](adr/0061-heartbeat-and-restore-marker.md)). Backups hold personal data and are not encrypted, but leave out the export and import files under the media root, which live for hours; the operator protects the volume and any copy of it ([privacy.md](../privacy.md#backups)) |
| Browser | Simple Content Security Policy: `style-src` is `'self'` plus a per-request nonce, emitted only on a page with the block of custom colours, and only validated hex values reach that block ([ADR-0054](adr/0054-branding-owned-by-domain-and-theme.md)); images may load from `https:`, for quizzes that load them from their server ([ADR-0043](adr/0043-external-images.md)) |
| Fetching addresses | HTTPS only, internal addresses refused unless a global switch allows them, each redirect checked again, connection to the checked address. Any admin can turn the switch on ([ADR-0043](adr/0043-external-images.md)) |
| Result integrity | Server never accepts client-computed score, correct solution or completion time as truth; signed attempt tokens ([ADR-0024](adr/0024-attempt-token-signing.md)); idempotent submission ([ADR-0009](adr/0009-server-authoritative-scoring-signed-token-idempotent-submit.md)) |
| Uploads | Admin: basic check for SVG and GIF, raster rebuilt and shrunk; every stored file is served with `nosniff` and `Content-Security-Policy: sandbox`. Participant: raster only, rebuilt from pixels, shrunk, with a per-run total limit ([ADR-0028](adr/0028-upload-limits.md)) |
| XSS | Jinja2 autoescape on all pages. Plugin output is marked safe, so the shared contract suite tests that each question type escapes admin-entered text ([ADR-0039](adr/0039-installed-modules-are-trusted-code.md)) |
| CSV | Escaping and formula-injection protection on export; a ZIP is never unpacked to disk, its names are only compared with cells, and its limits hold whatever it declares ([ADR-0045](adr/0045-csv-one-file-and-failed-images.md)) |
| Access code | Stored only as a password hash and shown to the admin once. A signed cookie per run remembers a correct code and stops working when the code changes. Failed codes: 10 per minute per client IP in process memory (`KVZ_CODE_ATTEMPTS_PER_MINUTE`); the IP is the first `X-Forwarded-For` value, which Caddy overwrites, else `REMOTE_ADDR`. A locked start is refused before any name check or participant row ([ADR-0049](adr/0049-participants-and-access-code.md)) |
| Participant identity | Cookies `HttpOnly`, `SameSite=Lax`, `Secure` outside debug. Only an HMAC of the key with the run id is stored. A refused fill-in under `/v/<token>` answers 200 so no request log holds the token; pages echoing a typed name or e-mail are `private, no-store` ([ADR-0049](adr/0049-participants-and-access-code.md)) |
| Participant photos | Private assets: `/media/<id>` answers 404, served only through routes that check the right, `Cache-Control: private, no-store`. A form field cannot name an asset. A photo reaches the server only through `submit`, which is limited per client address, plus the per-run image limit and, in Caddy, the 16 MB and 101 MB body limits ([ADR-0047](adr/0047-image-answer-photo-visibility.md), [ADR-0028](adr/0028-upload-limits.md)) |
| Result link and walkthrough | The private link is a signed reference to one attempt, no indexing, no referrer, absent from logs through status 200 and 204. The walkthrough exists only after a normal run ended, and names no participant ([ADR-0046](adr/0046-stored-answers-and-who-sees-them.md)) |
| Test links | Anyone with the address sees the questions and plays without an account, in a run that counts for nothing. Random 32 bytes, kept readable so the admin can copy it again, absent from logs and audit, no indexing, no referrer ([ADR-0044](adr/0044-preview-and-test-links.md)) |
| Data exposure | E-mail never public, never sent to external analytics; only allowed scoreboard columns public |
| Logs | No answers or PII in operational logs. The new log lines of the heartbeat, the pass record, the restore marker and `prune` carry counts and exception types only, never a path, an address or a name; a malformed result photo address answers 204 so that no 404 logs the token in its path ([ADR-0061](adr/0061-heartbeat-and-restore-marker.md)) |
| Secrets | Configuration via environment and secrets; nothing secret in repo ([../deployment.md](../deployment.md)) |

### Limits of public routes

A request limit counts per client address (for login, per name and address, and per address alone) in one of five buckets
(`login`, `login_address`, `code`, `submit`, `start`; `app/api/rate_limit.py`). `tests/api/test_request_limits.py`
lists every public route that answers a POST (admin routes are covered by login and CSRF) and fails
when a new one is not declared there or when a declared one no longer exists.

The client address is the first `X-Forwarded-For` value, else `REMOTE_ADDR`. That is safe only
because the application is reachable through Caddy alone (the compose topology), which replaces any
`X-Forwarded-For` a client sends with the real address. Counters live in process memory and reset on
a restart ([ADR-0058](adr/0058-rate-limit-buckets.md)). The login takes its slot in `login` and
`login_address` before the password is checked and gives both back on a correct login, so parallel
wrong guesses cannot pass the limit and a correct login counts toward nothing
([ADR-0060](adr/0060-login-reservation-and-address-ceiling.md)). The ceiling `login_address` counts
wrong logins of all names from one address (30 a minute), so a spray over many names is bounded; it
is per address and never per account, and a restart clears it. Known limit: at the defaults one
address can create 300 attempts a minute.

- `start`: bucket `start`. It creates an attempt, and a participant for a new browser.
- `submit`: bucket `submit`. It scores an attempt and stores its answers and photos.
- `run_code`: bucket `code`, counting wrong codes only.
- Admin login: buckets `login` (per name and address) and `login_address` (per address), counting failed attempts; the slots are taken before the password is checked.
- `resume`, `check`, `attempt_time`: unlimited. Each needs the signed attempt token and writes no
  row or file; `resume` issues a fresh token for an attempt that already exists.
- `switch`: unlimited. It needs the signed attempt token and creates at most one replacement attempt
  per change of the run's current revision (publishing, or a return to an older revision), since
  the replacement is already on the current revision.
- `result_identity`: unlimited. It needs the signed result token and fills in only the name or
  e-mail still missing on an existing participant.
- Pages, scoreboard, results, media, assets and `healthz`: unlimited. They only read, and any body
  sent to them is ignored.

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

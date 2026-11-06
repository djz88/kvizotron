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
| Admin requests | Django CSRF protection on authenticated state-changing operations; backend authorisation checks |
| Abuse | Login attempt limiting, submit rate limit, access-code attempt limiting ([ADR-0030](adr/0030-rate-limit-thresholds.md)) |
| Browser | Simple Content Security Policy |
| Result integrity | Server never accepts client-computed score, correct solution or completion time as truth; signed attempt tokens ([ADR-0024](adr/0024-attempt-token-signing.md)); idempotent submission ([ADR-0009](adr/0009-server-authoritative-scoring-signed-token-idempotent-submit.md)) |
| Uploads | Admin: basic check for SVG and GIF, raster shrunk. Participant: raster only, rebuilt from pixels, shrunk, with a per-run total limit ([ADR-0028](adr/0028-upload-limits.md)) |
| XSS | Protection against XSS in admin-entered and imported text |
| CSV | Escaping and formula-injection protection on export ([providers/csv-io.md](providers/csv-io.md)) |
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

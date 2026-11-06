# Overview

| | |
|---|---|
| **Product name** | Kvízotron (technical name without diacritics: `kvizotron`) |
| **Official slogan** | „Zapni mozek. Spusť Kvízotron.“ (EN: "Switch on your brain. Start Kvízotron.") |
| **Type** | Self-hosted; public participation without registration; local administration |
| **Target capacity** | ~50 concurrent participants |
| **Priorities** | Simple operations, full modularity of functional capabilities, proportionate data protection, result integrity |
| **Spec status** | Consolidated specification for implementation, v1.0 (2026-11-04) |

## Goal

Administrators create and publish multilingual quizzes. The public fills them in via a web address or
QR code. Identity and results can optionally be stored, and competitions can be held with a
scoreboard, rewards and an auditable prize draw. The application runs on the operator's own Linux
server or in Docker Compose, on the operator's own domain.

## Scope of v1.0

Part of v1.0 (delivered in stages, see [roadmap.md](roadmap.md)):

- all functions confirmed in the decision rounds;
- modular interfaces for further functions ([modules/contracts.md](modules/contracts.md));
- one shipped theme;
- CSV import **and** export;
- separate test mode and preview;
- published immutable revisions;
- independent competition runs.

## Out of scope for v1.0 (LATER) — contracts anticipated

Direct Google Sheets/Workspace integration, video question type, additional themes, SSO/OIDC,
e-mail automation, voucher codes, JSON export.

These **MUST NOT** require a kernel change — only delivery of a module and, where needed, its
migrations.

## Explicit non-guarantees

- An anonymous cookie cannot reliably guarantee one participation per natural person, nor prevent
  use of multiple devices ([ADR-0011](adr/0011-anonymous-cookie-participant-identity.md)).
- The prize draw is auditable at the application-log level; it is **not** cryptographically
  indisputable towards the database administrator ([ADR-0013](adr/0013-manual-draw-csprng-append-only-audit.md)).

## Quality attributes

| Attribute | Target / approach | Where |
|---|---|---|
| Operability | Single app container + reverse proxy, SQLite | [ADR-0015](adr/0015-docker-compose-caddy-systemd-alt.md), [../deployment.md](../deployment.md) |
| Modularity | Minimal kernel, every capability behind a contract incl. auth and persistence | [ADR-0002](adr/0002-modular-monolith-minimal-kernel.md) |
| Integrity | Server-authoritative scoring, signed attempt token, idempotent submission | [ADR-0009](adr/0009-server-authoritative-scoring-signed-token-idempotent-submit.md) |
| History safety | Immutable revisions, restart = new run | [ADR-0006](adr/0006-separate-quiz-revision-run-attempt-immutable-revisions.md), [ADR-0007](adr/0007-restart-creates-new-run-keeps-history.md) |
| Privacy | Configurable retention profiles, data minimisation, stateless mode | [ADR-0012](adr/0012-configurable-retention-profiles-and-stateless-mode.md), [../privacy.md](../privacy.md) |
| Performance | 50 concurrent participants incl. simultaneous submissions; mandatory load test | [AC-15](acceptance-criteria.md) |
| Accessibility / UX | Mobile-first, keyboard accessible, cs/en/uk public UI | [modules/api-ui.md](modules/api-ui.md) |
| Security | Proportionate: Argon2id, CSRF, CSP, upload checks, audit | [security.md](security.md) |

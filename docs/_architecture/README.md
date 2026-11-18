# Kvízotron — Architecture Documentation

Kvízotron is a self-hosted, multilingual quiz and competition platform. Public participants play
without registration (web URL or QR code); local administrators author quizzes, run competitions with
scoreboards, rewards and auditable prize draws.

This directory is the single source of truth for the v1.0 architecture. It replaces the original
consolidated product/technical specification v1.0 (Czech, 2026-11-02, last update 2026-11-04,
brainstorming rounds 1–5 + clarifications 45–47).

## Reading order

1. [overview.md](overview.md) — goals, scope, non-goals, quality attributes
2. [modules/domain.md](modules/domain.md) — core domain concepts and lifecycles
3. [architecture.md](architecture.md) — system views, runtime flows, code layout
4. [modules/](modules/) — core: [kernel](modules/kernel.md), [contracts](modules/contracts.md), [domain](modules/domain.md), [api-ui](modules/api-ui.md)
5. [providers/](providers/) and [plugins/](plugins/) — reference modules (one file each)
6. [data-model.md](data-model.md), [security.md](security.md)
7. [adr/](adr/) — Architecture Decision Records (MADR 4)
8. [roadmap.md](roadmap.md), [acceptance-criteria.md](acceptance-criteria.md), [open-questions.md](open-questions.md), [TECH_DEBT.md](TECH_DEBT.md)

Related documents outside this directory:

- [../plugin-api.md](../plugin-api.md) — plugin manifest, contract Protocols, how to write and test a plugin
- [../deployment.md](../deployment.md) — runtime, Docker Compose, Caddy, backups, operations
- [../privacy.md](../privacy.md) — personal data collection, retention, privacy notice

## Requirement keywords

| Keyword | Meaning |
|---|---|
| **MUST** | Required for v1.0. |
| **SHOULD** | Recommended realisation; may be replaced by an equivalent implementation that keeps contracts and behaviour. |
| **LATER** | Explicitly out of v1.0. |

Identifiers are stable anchors: functional requirements `FR-01`…`FR-54`, acceptance criteria
`AC-01`…`AC-185`, decisions `ADR-NNNN`, open questions `OQ-NN`,
technical debt `TD-NNN`. Each `FR-xx` is **defined in exactly
one file** (see the index below); other files only reference it.

## Requirement index

| Requirements | Defined in |
|---|---|
| FR-01 – FR-04, FR-50, FR-51, FR-53 | [modules/api-ui.md](modules/api-ui.md) |
| FR-05, FR-14 | [plugins/theme-default.md](plugins/theme-default.md) |
| FR-06 | [security.md](security.md) |
| FR-07 | [providers/auth-local.md](providers/auth-local.md) |
| FR-08 – FR-13, FR-47 – FR-49, FR-52 | [modules/domain.md](modules/domain.md) |
| FR-15, FR-16, FR-18 – FR-20, FR-23, FR-45, FR-54 | [plugins/question-types.md](plugins/question-types.md) |
| FR-17, FR-22 | [plugins/quiz-flow.md](plugins/quiz-flow.md) |
| FR-21 | [providers/media-local.md](providers/media-local.md) |
| FR-24 – FR-26 | [plugins/scoring.md](plugins/scoring.md) |
| FR-27, FR-28 | [plugins/participants.md](plugins/participants.md) |
| FR-29 – FR-31, FR-43 | [plugins/results.md](plugins/results.md) |
| FR-32 – FR-35 | [../privacy.md](../privacy.md) |
| FR-36 | [plugins/rewards.md](plugins/rewards.md) |
| FR-37 – FR-39 | [plugins/drawings.md](plugins/drawings.md) |
| FR-40 – FR-42, FR-44 | [providers/csv-io.md](providers/csv-io.md) |
| FR-46 | [modules/kernel.md](modules/kernel.md) |

FR-45 and later and AC-16 and later were added after the original specification.

## Glossary

Domain terms (**Quiz**, **QuizRevision**, **QuizRun**, **Attempt**, **Participant**, **Scoreboard**)
are defined in [modules/domain.md](modules/domain.md#core-concepts--must-not-be-conflated).

| Term | Meaning |
|---|---|
| **Module** | Installed unit implementing registered contracts (ports): a provider or a plugin. |
| **Provider** | Module supplying infrastructure (database, auth, import/export); selected by the operator, changed on restart ([ADR-0037](adr/0037-providers-and-plugins.md)). |
| **Plugin** | Module supplying a product feature (question type, theme, result view); several can be active, enabled by an admin. |
| **Kernel** | Minimal core: bootstrap, process config, contract registry/verification, dependency resolver, event dispatch, module lifecycle. |
| **Test mode** | Isolated test attempts that never count towards public results, rewards or statistics. |
| **Preview** | Rendering of a quiz without writing any results. |
| **PII** | Personally identifiable information (nickname, e-mail, cookie key hash). |

## References (verified sources used for technical decisions)

- Django — databases, SQLite notes: https://docs.djangoproject.com/en/6.1/ref/databases/
- Django — custom authentication and user model: https://docs.djangoproject.com/en/6.1/topics/auth/customizing/
- Django — sessions: https://docs.djangoproject.com/en/6.1/topics/http/sessions/
- Django — cryptographic signing: https://docs.djangoproject.com/en/6.1/topics/signing/
- Django — templates and the Jinja2 backend: https://docs.djangoproject.com/en/6.1/topics/templates/
- SQLite WAL — concurrent reads, single writer: https://www.sqlite.org/wal.html
- HTMX — documentation: https://htmx.org/docs/
- Caddy — HTTPS reverse proxy: https://caddyserver.com/docs/quick-starts/reverse-proxy
- OWASP — Password Storage / Argon2id: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html

> This documentation captures consolidated product decisions and a recommended realisation. It is
> neither a finished implementation nor a legal assessment of any specific personal-data processing.

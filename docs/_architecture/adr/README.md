# Architecture Decision Records

Format: [MADR 4](https://adr.github.io/madr/). Template: [0000-template.md](0000-template.md).

| ADR | Title | Status |
|---|---|---|
| [ADR-0001](0001-record-architecture-decisions.md) | Record architecture decisions as MADR in docs/_architecture/adr | accepted |
| [ADR-0002](0002-modular-monolith-minimal-kernel.md) | Modular monolith with a minimal kernel | accepted |
| [ADR-0003](0003-python-fastapi-jinja-htmx.md) | Python with FastAPI, server-rendered Jinja2 and HTMX | superseded by ADR-0036 |
| [ADR-0004](0004-entry-points-typed-registry-pydantic.md) | Python entry points for discovery, typed registry ports, Pydantic contracts | accepted |
| [ADR-0005](0005-sqlite-wal-sqlalchemy-alembic-behind-persistence-provider.md) | SQLite (WAL) via SQLAlchemy 2.x and Alembic behind PersistenceProvider | superseded by ADR-0036 |
| [ADR-0006](0006-separate-quiz-revision-run-attempt-immutable-revisions.md) | Separate Quiz, QuizRevision, QuizRun, Attempt; published revisions are immutable | accepted |
| [ADR-0007](0007-restart-creates-new-run-keeps-history.md) | Restart of a competition creates a new QuizRun and keeps history | accepted |
| [ADR-0008](0008-scoreboard-revision-modes-default-separate.md) | Per-run scoreboard revision mode, default SEPARATE_BY_REVISION | superseded by ADR-0065 |
| [ADR-0009](0009-server-authoritative-scoring-signed-token-idempotent-submit.md) | Server-authoritative scoring with signed attempt token and idempotent submission | accepted |
| [ADR-0010](0010-strict-server-side-deadline.md) | Strict server-side deadline and attempt time limit | accepted |
| [ADR-0011](0011-anonymous-cookie-participant-identity.md) | Anonymous cookie as participant identity, without uniqueness guarantee | accepted |
| [ADR-0012](0012-configurable-retention-profiles-and-stateless-mode.md) | Configurable retention profiles per run, including a stateless mode | accepted |
| [ADR-0013](0013-manual-draw-csprng-append-only-audit.md) | Manual prize draw with CSPRNG and append-only audit | accepted |
| [ADR-0014](0014-local-admin-auth-argon2id-equal-roles.md) | Local admin accounts with Argon2id and equal permissions | accepted |
| [ADR-0015](0015-docker-compose-caddy-systemd-alt.md) | Docker Compose with Caddy; systemd as alternative | accepted |
| [ADR-0016](0016-in-process-events-no-broker.md) | Synchronous in-process events, no message broker | accepted |
| [ADR-0017](0017-preview-vs-isolated-test-mode.md) | Preview and isolated test mode, admin chooses | accepted |
| [ADR-0018](0018-locales-cs-en-uk-per-quiz-required.md) | Locales cs/en/uk with per-quiz required languages | accepted |
| [ADR-0019](0019-csv-import-export-json-in-field-draft-output.md) | CSV import/export with JSON-in-field for complex structures; import creates drafts | accepted |
| [ADR-0020](0020-browser-local-resume-untrusted.md) | Browser-local resume of unsubmitted attempts, treated as untrusted | accepted |
| [ADR-0021](0021-plugin-manifest-and-versioning.md) | Plugin manifest with separate contract and config-schema versions | accepted |
| [ADR-0022](0022-python-version.md) | Python version baseline | accepted |
| [ADR-0023](0023-id-format.md) | Entity identifier format | accepted |
| [ADR-0024](0024-attempt-token-signing.md) | Attempt token signing mechanism | accepted |
| [ADR-0025](0025-deadline-boundary-second-semantics.md) | Deadline boundary-second semantics | accepted |
| [ADR-0026](0026-scoreboard-tie-break-rule.md) | Scoreboard and best-attempt tie-break rule | accepted |
| [ADR-0027](0027-demo-alternative-persistence-provider.md) | Demonstration alternative provider | accepted |
| [ADR-0028](0028-upload-limits.md) | Upload rules and limits | accepted |
| [ADR-0029](0029-default-retention.md) | Default retention period | accepted |
| [ADR-0030](0030-rate-limit-thresholds.md) | Rate-limit thresholds | accepted |
| [ADR-0031](0031-public-links-to-archived-results.md) | Public links to archived run results | accepted |
| [ADR-0032](0032-csv-schema.md) | Import and export formats | accepted |
| [ADR-0033](0033-image-answer-question-type.md) | Image answer question type with mixed scoring | accepted |
| [ADR-0034](0034-module-requirements-on-settings.md) | Modules declare requirements on quiz and run settings | accepted |
| [ADR-0035](0035-immediate-solutions-only-without-competition.md) | Immediate solutions only without competition | accepted |
| [ADR-0036](0036-django-web-framework-and-orm.md) | Django as web framework and ORM | accepted |
| [ADR-0037](0037-providers-and-plugins.md) | Providers and plugins are separate module kinds | accepted |
| [ADR-0038](0038-revision-switch-policy-and-settings.md) | Policy for a new revision during an open round; settings with quiz override | accepted |
| [ADR-0039](0039-installed-modules-are-trusted-code.md) | Installed modules are trusted code | accepted |
| [ADR-0040](0040-question-types-grade-and-strategies-weigh.md) | Few question types with settings; types grade and strategies weigh | accepted |
| [ADR-0041](0041-draw-rows-and-flow-settings.md) | Draw rows set points; flow settings apply immediately and freeze on the attempt | accepted |
| [ADR-0042](0042-settings-inherited-and-declared.md) | Settings are inherited global → quiz → question, and every module declares its own | accepted |
| [ADR-0043](0043-external-images.md) | External images are copied by default, and a mode decides what a participant gets | accepted |
| [ADR-0044](0044-preview-and-test-links.md) | Preview stores nothing, and a test link is a hidden run fixed to one version | accepted |
| [ADR-0045](0045-csv-one-file-and-failed-images.md) | One import file with a quiz row, question export in Stage B, and a failed image keeps its question | accepted |
| [ADR-0046](0046-stored-answers-and-who-sees-them.md) | Stored answers, who sees them, a private link and a public walkthrough | accepted |
| [ADR-0047](0047-image-answer-photo-visibility.md) | Photo visibility chosen by the admin, automatic points as a share, grading in Stage B | accepted |
| [ADR-0048](0048-run-timing.md) | Run schedule without a background process, a limit fixed on the run, one time zone | accepted |
| [ADR-0049](0049-participants-and-access-code.md) | Participants identified per run only when needed, an access code per run | accepted |
| [ADR-0050](0050-data-profile-and-local-resume.md) | One data profile per run, a retention period without a job, local resume on by default | accepted |
| [ADR-0051](0051-scoreboard-participants-and-official-attempt.md) | A visible scoreboard identifies browsers, one official attempt each, anonymised live names | accepted |
| [ADR-0052](0052-setting-groups-levels-and-step-default.md) | Settings in named groups with a basic level, pages of questions, one question at a time by default | accepted |
| [ADR-0053](0053-rewards-tiers-alternates-and-draw-history.md) | Rewards copied onto the run, tiers by setting, alternates drawn at once, a draw history that only grows | accepted |
| [ADR-0054](0054-branding-owned-by-domain-and-theme.md) | Branding owned by the domain, palettes and derivation by the theme, colours that resolve with their palette | accepted |
| [ADR-0055](0055-results-export-background-job-and-csv-dialect.md) | Results export as a background job in the app process, a semicolon CSV dialect, and a table port for Google Sheets | accepted |
| [ADR-0056](0056-retention-job-summary-held-runs.md) | Hourly retention in a `jobs` service, a summary in place of deleted rows, held runs and an e-mail fingerprint | accepted |
| [ADR-0057](0057-plugin-admin-reasons-locks-no-configuration-table.md) | Modules page with shared refusal reasons, always-on plugins, and no configuration table yet | accepted |
| [ADR-0058](0058-rate-limit-buckets.md) | Four request-limit buckets, a start limit, what a refusal looks like, and the proxy keep-alive | accepted |
| [ADR-0059](0059-backup-and-restore.md) | A daily verified backup from the `jobs` service and a manual restore that keeps what it replaces | accepted |
| [ADR-0060](0060-login-reservation-and-address-ceiling.md) | Login slots reserved before the password is checked, a ceiling per address, and a repeated automatic submission | accepted |
| [ADR-0061](0061-heartbeat-and-restore-marker.md) | Heartbeat files and a pass record, a marker for an interrupted restore, and an address key for the erasure search | accepted |
| [ADR-0062](0062-quiz-type-port.md) | Quiz types as named bundles of quiz settings behind a `quiz_type` port | accepted |
| [ADR-0063](0063-kept-score.md) | Kept score: the last attempt or the average of all, one `Kept` value for every consumer | accepted |
| [ADR-0064](0064-run-copies-flow-and-profile.md) | A run copies its flow, sources and answers visibility when planned or opened | proposed |
| [ADR-0065](0065-scoreboard-by-percent-and-shared-boards.md) | One scoreboard by percent across revisions by default, and a shared board of several runs | accepted |
| [ADR-0066](0066-single-container-image.md) | A single-container image beside the Compose deployment | accepted |
| [ADR-0067](0067-quiz-title-and-public-address.md) | A quiz title is unique among active quizzes, and a quiz can name its public address | accepted |

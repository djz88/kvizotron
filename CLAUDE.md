# Kvízotron — instructions for agents

`AGENTS.md` is a symlink to this file.

Project type: self-hosted web application in Python (Django) — **stage A, milestones B1, B1.5, B2, B3, B4, B5, B6, C1, C2, C3, C4, C4.5, C5, D1, D2, D3, D4 and D5 done: admin UI, quizzes in three languages, safe changes to a quiz while it runs, navigation and look, question types Choice and Matching, images, scoring and sources, question banks, flow modes, answer reveal, images from a URL, preview, test links, import and export of questions, types Number, Text and Photo, photo rating, stored answers, private result link, public walkthrough, run schedule, deadline, time limit with a countdown, run archiving, participants and access code, data profile, no-storage mode, retention period, resuming in the browser, public leaderboard, run statistics and comparison, simplified administration, paged flow, logo, rewards and drawings, custom name, motto and colors, results export, deleting run data, erasure request, module management, request limits, headers, daily backup and restore, and load test**
Manifests: `pyproject.toml`, `uv.lock`

## Documentation

The source of truth for the architecture is `docs/_architecture/`; start at `docs/_architecture/README.md`.

- `docs/_architecture/overview.md` — goals, v1.0 scope, what is out of scope
- `docs/_architecture/architecture.md` — views of the system, start/submit flow, stack, code structure
- `docs/_architecture/modules/` — the core: kernel, contracts, domain, API and UI
- `docs/_architecture/providers/` — reference providers (infrastructure), one file per provider
- `docs/_architecture/plugins/` — reference plugins (features), one file per plugin
- `docs/_architecture/data-model.md`, `docs/_architecture/security.md`
- `docs/_architecture/adr/` — decisions in MADR 4 format
- `docs/_architecture/roadmap.md`, `acceptance-criteria.md`, `open-questions.md`
- `docs/_architecture/TECH_DEBT.md`, `TECH_DEBT_archive.md` — knowingly deferred unfinished work
- `docs/plugin-api.md`, `docs/deployment.md`, `docs/privacy.md`

Directories in `app/`, `tests/` and `tools/` have their own `CLAUDE.md`: what is in them, what is not, and what they may import. Only what concerns the whole project is here.

## Overview

Kvízotron is a platform for multilingual quizzes (cs/en/uk) and competitions. The public plays without registration via a URL or a QR code. Local admins create quizzes, start competitive runs with a leaderboard and rewards, and carry out auditable drawings. The target capacity is about 50 concurrent participants.

The architecture is a modular monolith with a minimal kernel: all functional areas, including authentication and persistence, are modules behind contracts. Modules are of two kinds: providers (infrastructure: database, auth, import/export) and plugins (features: question types, themes, result displays). Stack: Django, gunicorn, Jinja2, HTMX, Pydantic, SQLite (WAL), Caddy, Docker Compose.

Status: stage A (milestones A1–A4), B1, B1.5, B2, B3, B4, B5, B6, C1, C2, C3, C4, C4.5, C5, D1, D2, D3, D4 and D5 are done. What exists: kernel, providers, admin UI, playing a quiz in cs/en/uk with the types Choice and Matching, image upload, scoring part by part, sources on the result, QR, score on the server, settings with an override per quiz, switching a running run to a new revision, a change overview, return to an older revision, duplicating and archiving a quiz, quiz description, a main button by state, five color sets, a public menu, question banks with draws without repetition, shuffling, three flow modes with a progress indicator, answer reveal, a translated explanation, images from a URL as a copy or from their server, settings with an override per question, preview without saving, test links to a chosen version, import of questions from CSV and ZIP and their export, types Number, Text and Photo, photo rating per question or per attempt, a choice of storing and visibility of answers, a private result link, a public walkthrough after the run ends, module requirements for settings, a run schedule with a start and a deadline, an attempt time limit with a countdown and automatic submission, run archiving, one configured time zone, repeat rules with an anonymous cookie only where the run needs it, collecting a name and e-mail before the start or at the end, a ban on identical nicknames, an access code for a run stored only as a hash and an attempts table on the run, one data profile on the run (nothing, score, answers, detailed) instead of `store_answers`, a no-storage mode that deletes the attempt after submission and still counts it, a retention period stored on the run and resuming after a page reload from a copy in the browser that is no longer than 24 hours, a public run leaderboard (hidden, during the run, after the end) with one official attempt per browser, anonymous names during the run, ties by ADR-0026, revision modes with merging and a projector, run statistics, run comparison and sorting of the attempts table, a Basic / All switch with seven settings groups, a run schedule showing only differences, tabs with "More", a paged flow of N questions per page, a default flow of one question per page for new installations, a logo in the bar and on the About page, rewards by threshold, participation, manually and by drawing, copied to the run from the quiz template or from a previous run, claims from the official attempt with pickup instructions on the result, setting several thresholds and contact with winners, and a manual drawing with substitutes, a shift, a substitute winner and a new drawing in a history that does not change, with publishing winners on the leaderboard, a custom name, motto, logo, colors and footer globally with a per-field override on the quiz, colors computed to WCAG AA and a single footer line on every public page (administrator text, license, Python, Django and HTMX badges, "Runs on Kvízotron" with the version, the year and a public contact e-mail that, when not set, takes the e-mail of the quiz author's account), an optional administrator e-mail, the author of a quiz filled in retroactively too, and a section panel on the settings pages with a Basic / All switch, export of the results of one run, of all runs or of selected runs to CSV with a semicolon and a BOM (attempts, participants, question statistics, answers, reward claims and drawing history) as separate files or in a ZIP with photos, prepared by a background thread and available for download for 24 hours only to the administrator who requested it, and a contract for Google Sheets without an implementation, hourly deletion of run data after the retention period expires in the `jobs` service in short transactions with an anonymous summary for statistics, a move to the archive and a record without personal data, runs already past the period held until the administrator confirms, "Delete data now", an erasure request across runs by e-mail (a lookup by one query on `Participant.email_key`, the leaderboard cache is cleaned after the erasure) or by nickname, with a hash of the e-mail in the record, a Deletion history and a deletion date on the run, a Modules page with switching plugins, reasons for rejection and a lock on plugins without which the application does not work, an overview of module settings with a listing of where a value differs from the global one, request limits by client address in five buckets in process memory (login: failures only, by name and address, plus a ceiling per address across names, the slot is taken before the password is checked and is returned on a correct login; wrong code; submit; start; 429 with `Retry-After`, every public route with a POST has a bucket or a reason in a test, ADR-0058), automatic submission at the end of the time, which the page repeats after a connection error, 5xx and 429 with the same key (it only saves what is repaired within the 5 s reserve before the end; `start` is not repeated; ADR-0060), HSTS for six months and a tested set of response headers including `frame-ancestors 'none'`, Caddy, which closes idle connections to the application earlier than gunicorn, a daily database backup (the SQLite backup API) and media backup from the `jobs` service into the `backups` volume, verified and written to disk before it is published, with deletion after `KVZ_BACKUP_RETENTION_DAYS` after every attempt and the newest valid backup always kept, a manual restore `manage.py restore <date|latest>` that refuses a damaged backup, an older schema, a database in use, a running `app` or `jobs` (a heartbeat in a file next to the database younger than 60 s) and an earlier unfinished restore (a `.restoring` marker in `pre-restore-<time>`, which `prune` never deletes) and leaves the old data in `pre-restore-<time>` (ADR-0059, ADR-0061), a visible pass of the `jobs` service (a record of the start, end and result, the healthcheck `python -m app.domain.heartbeat check` and a "Last pass" line on the Deletion history, ADR-0061), `manage.py backup`, which, when there is a directory that `prune` did not delete, prints the count and ends with an error, a load test of 50 participants with photos as a thread test in `make test` and `make load` with a backup during submission, a restore rehearsal and an address check, a single configuration overview `docs/configuration.md` guarded by a test, and AC-03 to AC-18 named by tests, a private photo address on the result that logs nothing when its shape is wrong, and no orphaned photo files when saving fails. After D5 came quiz types (ADR-0062, AC-171): seven named quiz settings sets from the `quiz_types` plugin behind the `quiz_type` port (Practice, Final test, Exam with a resit, Mock test, Contest, Pub quiz and Basic quiz, which returns a quiz to the global settings), choosing a type when creating a quiz and later with a change overview and a confirmation, a bar with the number of deviations and ▲ marks on settings that differ from the type, setting conflict rules shared by forms and types (`app/domain/setting_rules.py`) and quiz duplication that copies the type and the quiz settings. Additions for tests (project B, ADR-0063, AC-172 to AC-175): a success threshold in percent (result, private link, attempts table, statistics, export, leaderboard), at most that many attempts and a ban on further ones after a success (`ParticipantPolicyPlugin` 1.1), the rules `last` and `average` for the valid result (`results.kept`) and answer reveal after the run closes on the private link from the closing plus 10 minutes (`attempts.LATE_UPLOAD_WINDOW`). From D5 the application is meant for public deployment in the Compose topology with Caddy, or as a single container behind an ingress (the `single` target in the `Dockerfile`, `manage.py serve`, ADR-0066), always with one application process (the limits take the N-th address of `X-Forwarded-For` from the right according to `KVZ_TRUSTED_PROXIES`, and count in process memory; HSTS and the request body ceiling are enforced by the application as well). No milestone remains before version 1.0: what remains are the release checks from `docs/deployment.md` (`make quality`, `make smoke`, `make load`, restore rehearsal, a walkthrough in a browser) and the triage of technical debt, which the user postponed until after D5 (`docs/_architecture/TECH_DEBT.md`); `make smoke` and `make load` wait about a minute longer after the start, because the healthcheck of the `jobs` service first runs after a minute.

## Commands

Works now:

- `make help` — list of targets
- `make hooks` — installs git hooks (pinned pre-commit) for commit, commit message and push
- `make private-traces` — creates an empty `.git/info/private-traces` for personal words that the hooks reject; leaves an existing one alone
- `make env-update` — installs the versions the project declares: uv (`[tool.uv] required-version`), Python and packages (`uv.lock`), pre-commit with hooks, Docker images; promotes nothing above that; `make doctor` points to it
- `make setup` — installs dependencies; requires uv in the version from `pyproject.toml` (`make env-update`)
- `make setup-reset` — `make clean` and `make setup`; takes versions from `uv.lock`, does not promote them
- `make doctor` — verifies tools (uv, docker, hooks)
- `make clean` — deletes the build environment (`.venv`, tool caches, build outputs); `.env`, data, backups and worktrees are not deleted
- `make lint` — ruff and mypy; `make lint fix` fixes what it can
- `make test` — pytest
- `make secrets` — gitleaks on staged changes and in the git history; does not check files outside git
- `make quality` — lint, tests, gitleaks and the `TECH_DEBT.md` check; the same runs in CI
- `make smoke` — starts the deployment in Docker and verifies it
- `make load` — load test in Docker: 50 participants submit photos at once during a backup, a restore from a backup and an address check (project `kvizotron-load`, minutes; not part of `make quality`)
- `make wiring` — only the wiring checks (`tests/test_wiring.py`); they also run in `make test`
- `make plan-check plan=… base=main` — did the files the plan names change?
- `make messages` — extracts texts for translation and compiles the catalogs; `.po` and `.mo` are in git
- `make worktree`, `make worktree-create NAME`, `make worktree-remove NAME` — working copies in `.worktrees/`; the branch is deleted only when merged
- `make tech-debt-check`, `tech-debt-tidy`, `tech-debt-create title="…"`, `tech-debt-resolve id=TD-NNN` — working with `TECH_DEBT.md` and the archive

Do not invent other commands for these checks.

## Conventions

Name:

- The application is called **Kvízotron** (texts, UI, documentation). Technical names stay without diacritics: `kvizotron` (directory, git repository, packages, identifiers).

Language:

- Everything in the repository is in English: code, comments, docs, agent instructions, skills, Makefile help and tool messages. Czech stays only in `README.cs.md` and in user-facing texts (UI translations cs/uk and the tests that assert them), sample content for Czech users (e.g. `app/providers/csv_io/sample/`, test fixtures in deploy scripts) and the owner's trigger phrases quoted in skill descriptions. `tests/test_language.py` guards it.

Documentation:

- Documentation in `docs/` is in English, diagrams only as text or ASCII.
- Every fact has a single place, other files refer to it. The FR → file map is in `docs/_architecture/README.md`.
- The IDs `FR-xx`, `AC-xx`, `ADR-NNNN`, `OQ-xx` and `TD-NNN` are stable, do not change their meaning or reuse them.
- `FR-xx` is defined only once, as a bullet ``- `FR-xx` `` in the file given by the map.
- Binding level: MUST = a v1.0 requirement, SHOULD = a recommendation, LATER = outside v1.0.
- An ADR with the status `proposed` is not decided yet. Do not treat it as settled: before implementing the affected area, have a human decide it and update `open-questions.md`.
- An architecturally significant change adds a new ADR, or replaces the old one (`superseded by ADR-NNNN`).

A design the implementation must follow:

- New features belong in a module (a provider or a plugin, ADR-0037) behind a contract, not in the kernel. The kernel contains only bootstrap, configuration, the registry, contract verification, dependency resolution, events and the lifecycle.
- In the UI, `QuizRun` is called "běh" in Czech and "run" in English. The word "kolo" (round) is not used in texts.
- Do not mix up `Quiz`, `QuizRevision`, `QuizRun`, `Attempt`, `Participant` and `Scoreboard` (`docs/_architecture/modules/domain.md`).
- A published revision is immutable. Restarting a competition creates a new run and never takes over results.
- The score is always computed by the server; the client's score, the solution and the times are not trusted. `public_payload()` never contains the answer key.
- Every module must pass the shared contract tests in `tests/contracts/`.
- A new setting is inherited global → quiz → question, and a narrower scope must have a written reason (ADR-0042). Every module lists a `settings` field in its manifest, and if it has none, then `[]`; without it the tests do not pass. Where a setting belongs is decided by whoever adds it: the agent asks the user if the task does not say. The procedure is in the skill `kvizotron-add-setting`.

## Profile for dev-workflow

Profile: `kvizotron`. It tightens the classification of the `dev-workflow` skill; the agent reads it from here, nothing enforces it. The tier names stay as the skill uses them: `MALÁ` (small), `STŘEDNÍ` (medium), `VELKÁ` (large).

- Always VELKÁ: `app/contracts/`, `app/kernel/`, `app/domain/models.py` and migrations, the `manifest.py` of modules, `app/providers/auth_local/`, `deploy/compose.yaml`.
- At least STŘEDNÍ: `app/api/play.py`, `app/api/run_clock.py`, `app/domain/attempts.py`, `app/domain/tokens.py`. They govern what is accepted and how time and score are computed.
- Also always VELKÁ is a change that touches the UI and the domain at the same time, or that changes behavior described in an ADR.

## Project skills

In `.claude/skills/`: `kvizotron-milestone` (designing and closing a milestone), `kvizotron-add-setting` (a new setting), `kvizotron-add-module` (a new plugin or provider), `kvizotron-browser-walkthrough` (a walkthrough in a browser and the `kvizotron-browser` stack), `kvizotron-check-applied` (is everything used and wired, before `review-roles`), `kvizotron-check-integration` (flows across layers). The skills of this repository are named `kvizotron-*`; `tests/test_docs.py` guards that. The profile for `review-roles` is `.claude/review-profile.md`.

## Rules

- No secrets (passwords, tokens, keys) belong in code, configuration, logs or commits; they belong in environment variables or a secrets manager.
- Inputs from outside (user, network, files) are validated; errors are handled, not suppressed.
- A new dependency only with a reason and from a trusted source, with a pinned version.
- Before a commit, the repository checks pass (pre-commit, lint, tests), if the repository has them.
- Commands that delete data, rewrite git history or deploy something are run only with a human's consent. The hook `.claude/hooks/guard_docker_volumes.py` refuses to delete volumes of the `kvizotron-browser` stack and of a stack without a name, and asks for others.
- Participants' answers and personal data do not belong in logs; an e-mail is never published.
- Commit messages have no `Claude-Session` line or any other link to an agent session; `Co-Authored-By` stays. Documentation, plans and agent files (`docs/`, `.claude/`, `CLAUDE.md`) contain no local paths (home directory, the agent's temporary directories) or addresses from one's own network: use `<repo>`, `<scratchpad>` and an example address like `192.168.1.10:8443` instead. Paths and links are guarded by `tests/test_docs.py`; the commit, the commit message and the push are guarded by `tools/private_traces.py` (the hooks from `make hooks`), which also takes personal words from `.git/info/private-traces` outside git.

## Tests

- Every change of behavior has a test; fixing a bug starts with a test that shows the bug.
- Tests run through `make test` / `make quality` and must pass before a commit.
- Tests are not deleted or weakened to make them pass; skipping only with a stated reason.
- Tests do not depend on the network or on order; there are no real secrets in tests.

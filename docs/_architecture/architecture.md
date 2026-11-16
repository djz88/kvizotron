# Architecture

Style: **modular monolith with a minimal kernel** ([ADR-0002](adr/0002-modular-monolith-minimal-kernel.md)).
One Python web process, SQLite in WAL mode, local media volume, Caddy in front, a management CLI for
scheduled jobs.

## 1. System context

```
   +-------------------+         HTTPS (URL / QR)          +-----------------------------+
   |   Participant     | --------------------------------> |                             |
   | (anonymous, any   |   play quiz, submit, scoreboard   |                             |
   |  browser, mobile) | <-------------------------------- |         Kvízotron           |
   +-------------------+                                   |  (self-hosted, own domain)  |
                                                           |                             |
   +-------------------+         HTTPS (/admin)            |                             |
   |  Administrator    | --------------------------------> |                             |
   | (local account)   |   author, publish, run, draw,     |                             |
   +-------------------+   import/export, settings         +--------------+--------------+
                                                                          |
   +-------------------+                                                  | HTTPS GET (optional)
   |  Server operator  |  deploy, configure env/secrets,                  v
   | (shell access)    |  install plugins, backups, CLI          +-------------------+
   +-------------------+                                         | External HTTPS    |
                                                                 | media URLs        |
                                                                 +-------------------+
```

No outgoing e-mail, no external analytics, no SSO in v1.0.

## 2. Containers (deployment units)

```
                    Internet
                       |
                       v  :443 (auto TLS)
              +------------------+
              |      Caddy       |  reverse proxy, certificates
              +--------+---------+
                       | HTTP (internal network)
                       v
   +---------------------------------------------+        +---------------------------+
   |  app  (Django + Jinja2 + HTMX, gunicorn)     |        |  jobs (same image)         |
   |  kernel + enabled modules, single process    |        |  manage.py jobs: one       |
   |  healthcheck endpoint                        |        |  retention pass per hour,  |
   +-----------+-------------------+--------------+        |  in a Python loop;         |
               |                   |                       |  daily verified backup     |
               v                   v                       +-------------+-------------+
   +-------------------+   +-------------------+                         |
   | SQLite (WAL)      |   | media volume      | <-----------------------+
   | persistent volume |   | (uploaded files)  |
   +-------------------+   +-------------------+
```

Details and alternatives (systemd without Docker): [../deployment.md](../deployment.md),
[ADR-0015](adr/0015-docker-compose-caddy-systemd-alt.md).

## 3. Components inside the app

```
 +---------------------------------------------------------------------------------+
 | api/  (routing composition, thin views, HTMX partials)                          |
 +------------------------------------+--------------------------------------------+
                                      | calls typed ports by registry key
 +------------------------------------v--------------------------------------------+
 | domain/  Quiz · QuizRevision · QuizRun · Attempt · Participant · Scoreboard     |
 |          invariants, lifecycle, services (publish, start, submit, close, draw)  |
 +------------------------------------+--------------------------------------------+
                                      |
 +------------------------------------v--------------------------------------------+
 | kernel/  bootstrap · config · registry · contract verification ·                |
 |          dependency resolver · event dispatch · lifecycle                       |
 |  contracts/  versioned Protocols + Pydantic schemas                             |
 +--------------------+---------------------------------------+--------------------+
                      |                                       |
   providers/ (infrastructure)                 plugins/ (features)
   auth local · persistence sqlite ·           question types (8) · scoring basic/partial ·
   media local · retention local · csv io      quiz flow all/step · participants browser anon ·
                                               result views · rewards threshold ·
                                               draw manual · theme default
```

Per-component documentation: [modules/](modules/), [providers/](providers/) and [plugins/](plugins/).

## 4. Runtime flow: start and submit an attempt

Decision: [ADR-0009](adr/0009-server-authoritative-scoring-signed-token-idempotent-submit.md).

```
 Browser                          app (api → domain → modules)                    SQLite
   |  GET /q/{slug}                       |                                          |
   |------------------------------------->| load run + revision public snapshot      |
   |<-------------------------------------| (public_payload, no answer key)          |
   |  choose locale                       |                                          |
   |  POST /r/{run_id}/start              |                                          |
   |------------------------------------->| check run OPEN, access code, policy      |
   |                                      | pick questions/order from revision/bank  |
   |                                      | (frozen: FR-19)                          |
   |                                      |---- insert attempt (+attempt_question) ->| (if retention allows)
   |<-------------------------------------| signed attempt_token                     |
   |   {run_id, revision_id, attempt_id,  |                                          |
   |    started_at, expires_at,           |                                          |
   |    manifest_hash}  — no solutions    |                                          |
   |                                      |                                          |
   |  [optional] keep answers + token in  |                                          |
   |  localStorage, short TTL (FR-22)     |                                          |
   |                                      |                                          |
   |  POST /a/{attempt_id}/submit         |                                          |
   |  token + answers + submission_key    |                                          |
   |------------------------------------->| verify token signature                   |
   |                                      | verify time limits (FR-11), run state    |
   |                                      | verify manifest, answer schemas,         |
   |                                      | attempt rules, submission_key (replay)   |
   |                                      | re-score with versioned plugins          |
   |                                      |---- BEGIN short tx ---------------------->|
   |                                      |     store allowed data, results,          |
   |                                      |     reward entitlements                   |
   |                                      |---- COMMIT (retry/backoff on lock) ------>|
   |                                      | emit attempt.submitted                   |
   |<-------------------------------------| score, correct answers per policy,       |
   |                                      | reward entitlement, scoreboard access     |
```

Special cases:

- Without server persistence, the attempt limit cannot be guaranteed after cookie deletion or in
  another browser.
- With stored results, server-side `attempt_id`/`submission_key` provide idempotence.
- A newly published revision never changes a running attempt; its original snapshot is used
  ([AC-04](acceptance-criteria.md)).

## 5. Runtime flow: admin publishes a revision

```
 Admin ── edit DRAFT ──▶ validate (question-type plugins, required locales FR-03,
                         plugin compatibility) ──▶ build snapshot_json + plugins_json
                         + max_score + checksum ──▶ store PUBLISHED revision (immutable)
                         ──▶ previous revision SUPERSEDED ──▶ audit_event ──▶ quiz.published
```

## 6. Internal events

`quiz.published`, `run.opened`, `attempt.submitted`, `run.closed`, `draw.completed`,
`retention.executed` — synchronous and in-process ([ADR-0016](adr/0016-in-process-events-no-broker.md)).

## 7. Technology stack (summary)

| Layer | Technology | ADR |
|---|---|---|
| Language/runtime | Python 3.15 | [ADR-0022](adr/0022-python-version.md) |
| Web framework, sessions, CSRF, i18n, CLI | Django | [ADR-0036](adr/0036-django-web-framework-and-orm.md) |
| Application server | gunicorn, one worker process with threads | [ADR-0036](adr/0036-django-web-framework-and-orm.md) |
| Server-rendered HTML | Jinja2 through Django's template backend | [ADR-0036](adr/0036-django-web-framework-and-orm.md) |
| Interactivity | HTMX + small vanilla JavaScript without a build step for editors and specific questions | [ADR-0036](adr/0036-django-web-framework-and-orm.md) |
| Base styles | Pico CSS, vendored in the default theme ([THIRD_PARTY.md](../../THIRD_PARTY.md)) | [plugins/theme-default.md](plugins/theme-default.md) |
| Module registry | Python entry points + own typed registries/ports + Pydantic | [ADR-0004](adr/0004-entry-points-typed-registry-pydantic.md) |
| Module kinds | Providers (infrastructure) and plugins (features) | [ADR-0037](adr/0037-providers-and-plugins.md) |
| Data access | Django ORM and migrations; `PersistenceProvider` supplies database settings | [ADR-0036](adr/0036-django-web-framework-and-orm.md) |
| Database v1.0 | SQLite in WAL mode (local persistent volume) | [ADR-0036](adr/0036-django-web-framework-and-orm.md) |
| Auth | Local admins on Django auth, Argon2id password hashing | [ADR-0014](adr/0014-local-admin-auth-argon2id-equal-roles.md) |
| HTTPS | Caddy reverse proxy, automatic certificates; as a single container, the ingress in front of it | [ADR-0015](adr/0015-docker-compose-caddy-systemd-alt.md), [ADR-0066](adr/0066-single-container-image.md) |
| Run | Docker Compose; alternatively one container (`docker build --target single`, for example a Kubernetes pod) or systemd | [ADR-0015](adr/0015-docker-compose-caddy-systemd-alt.md), [ADR-0066](adr/0066-single-container-image.md) |
| Scheduled jobs | Compose service `jobs` looping `manage.py jobs`: one retention pass per hour (which also deletes expired login sessions) and one backup per local day; `manage.py retention` and `manage.py backup` for one by hand ([ADR-0056](adr/0056-retention-job-summary-held-runs.md), [ADR-0059](adr/0059-backup-and-restore.md)) | [providers/retention.md](providers/retention.md) |
| Media and backups | Local persistent volumes; a daily verified backup of the database (SQLite backup API) and the media into a `backups` volume that only `jobs` mounts, and a manual restore ([ADR-0059](adr/0059-backup-and-restore.md)) | [../deployment.md](../deployment.md#backup-and-restore) |

Not needed for this size: Redis, a Kubernetes-specific design (one replica in one container is enough, [ADR-0066](adr/0066-single-container-image.md)), message broker, external database.

## 8. Code layout (recommended)

```text
kvizotron/
  manage.py
  app/
    settings.py            # loads modules through kernel discovery
    urls.py, wsgi.py
    kernel/                # bootstrap, registry, contracts, dependency graph
    contracts/             # versioned public ports / schemas
    domain/                # quiz, revision, run, attempt models and invariants
    api/                   # routing composition; thin views
    providers/             # one Django app per provider
      auth_local/
      persistence_sqlite/
      media_local/
      csv_io/
      retention/
    plugins/               # one Django app per plugin
      questions/           # choice, image, ordering, matching, text, number...
      scoring/
      quiz_flow/
      quiz_types/
      participants/
      results/
      rewards/
      drawings/
      theme_default/
    jinja2/                # shared base layout
    static/
  tests/
    contracts/             # every module must pass the shared tests
    integration/
    e2e/
    load/
  deploy/
    compose.yaml
    Caddyfile
  docs/
  .github/               # CODEOWNERS, CI workflow
  Dockerfile
  Makefile               # single source of truth for CI (make quality)
```

(The spec used `quiz-app/` as root name; the repository is `kvizotron/`.)

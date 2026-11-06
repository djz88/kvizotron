# Deployment & Operations

Decision: [ADR-0015](_architecture/adr/0015-docker-compose-caddy-systemd-alt.md). Architecture view:
[_architecture/architecture.md](_architecture/architecture.md#2-containers-deployment-units).

## Topology

- **Docker Compose** (primary): `caddy` (reverse proxy, automatic HTTPS) + `app` (Django under gunicorn, single
  process) + persistent volumes for SQLite and media. Files: `deploy/compose.yaml`, `deploy/Caddyfile`.
- **systemd** (alternative): app as a service behind Caddy, without Docker. Documented only; not tested
  or supported like Compose.
- Runs on the operator's own Linux server and domain.

## Start

```sh
cp deploy/.env.example deploy/.env    # then fill in the values
docker compose -f deploy/compose.yaml up -d --build
```

A one-shot `migrate` service applies database migrations before `app` starts; Caddy starts when `app` is
healthy. The application serves its few static files itself, so no collect step is needed. Errors and warnings go to the container log (`docker compose logs app`).

`make smoke` runs the whole topology under a separate project name and removes only that project afterwards.

## Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `KVZ_DOMAIN` | yes | Public domain; Caddy obtains its certificate |
| `KVZ_SECRET_KEY` | yes | Django `SECRET_KEY`; generate with `openssl rand -hex 32`. Changing it: see [minimum operational elements](#minimum-operational-elements) |
| `KVZ_DB_PATH` | set by the image | SQLite file on the `db` volume |
| `KVZ_DEBUG` | no | `1` enables Django debug mode; never in production |
| `KVZ_HTTP_PORT`, `KVZ_HTTPS_PORT` | no | Published ports, default 80 and 443 |

## Modules

`manage.py modules` lists installed modules, enables or disables a plugin and runs the startup
verification:

```sh
docker compose -f deploy/compose.yaml run --rm app python manage.py modules list
docker compose -f deploy/compose.yaml run --rm app python manage.py modules disable <module id>
```

`run` also works while the application cannot start. It refuses to start while migrations are unapplied,
including after a new module is installed, and while an enabled module depends on a disabled one. Rules: [modules/kernel.md](_architecture/modules/kernel.md#module-installation-and-activation).

## Constraints

- Database volume constraints (local disk only, WAL, single writer): see
  [persistence-sqlite](_architecture/providers/persistence-sqlite.md).

## Minimum operational elements

- Docker healthcheck on `/healthz`, backed by `PersistenceProvider.healthcheck()`.
- Clear logs without answers or PII.
- Configuration via environment variables and secrets (never committed). `KVZ_SECRET_KEY` signs
  attempt tokens and the session hash. Change it only when no run is open: it invalidates attempts in progress
  and logs admins out ([ADR-0024](_architecture/adr/0024-attempt-token-signing.md)).
- SQL and asset backups with **verified restore**, made with SQLite's backup mechanism, never a plain
  file copy; backup retention limited so that deleted personal
  data are not restored without reason ([privacy.md](privacy.md)). Restored files **MUST** be owned by uid 1000,
  the application's user; otherwise `migrate` fails with `unable to open database file` and `app` does not start.
- Database migrations as part of the release process.
- One-time initialisation of the first admin, and a new password for a locked-out admin. Both ask for
  the password twice; scripts pipe it to `--password-stdin` instead. A password is never a command
  argument, and a reset also ends that admin's sessions:

  ```sh
  docker compose -f deploy/compose.yaml run --rm -it app python manage.py init_admin <login>
  docker compose -f deploy/compose.yaml run --rm -it app python manage.py reset_admin_password <login>
  ```
- Module versions locked in the deployment manifest.
- Monitor free disk space: a full disk also stops SQLite. Participant images have a per-run limit
  ([ADR-0028](_architecture/adr/0028-upload-limits.md)), but runs add up.
- Scheduled jobs (retention, cleanup) via management CLI + systemd timer/cron or a separate job process.

## Release checks (v1.0)

- Load test: 50 concurrent participants incl. simultaneous submissions ([AC-15](_architecture/acceptance-criteria.md)).
- Backup → restore drill.
- Configuration reference documented.

> Further environment variables and backup tooling are defined in Stage A/D.

# Configuration

Every environment variable of Kvízotron is listed here, and nowhere else. Deployment steps are in
[deployment.md](deployment.md). With Docker Compose, put the values in `deploy/.env` (start from
`deploy/.env.example`); `tests/test_configuration_docs.py` fails when a variable is read in the
code or in the deployment files without a row below.

## Environment variables

The last column says how a value reaches the program in `deploy/compose.yaml`: `app` means it is
passed to the application containers (`app`, `migrate` and `jobs`), `caddy` that the proxy gets it,
`compose` that Compose itself reads it, and `no` that Compose does not pass it, so it changes
nothing there.

An empty value means the default, for the numbers as well, and a number must be a whole number of at
least 1: anything else stops the application at start.

### Required

| Variable | Required | Default | Meaning | Read in | Compose |
|---|---|---|---|---|---|
| `KVZ_DOMAIN` | yes | none | Public domain; Caddy obtains its certificate and the application accepts this host name only (and `localhost`, which the container health check uses; Caddy forwards `KVZ_DOMAIN` only). A LAN IP address also works, with a certificate from Caddy's own local authority, so a browser warns until that authority is trusted | `app/settings.py`, `deploy/Caddyfile` | app, caddy |
| `KVZ_SECRET_KEY` | yes | none | Django `SECRET_KEY`, at least 32 characters (the app refuses to start with less); generate with `openssl rand -hex 32`. Changing it: see [minimum operational elements](deployment.md#minimum-operational-elements) | `app/settings.py` | app |

### Ports and time zone

| Variable | Required | Default | Meaning | Read in | Compose |
|---|---|---|---|---|---|
| `KVZ_HTTP_PORT` | no | `80` | Host port Caddy publishes for HTTP | `deploy/compose.yaml` | compose |
| `KVZ_HTTPS_PORT` | no | `443` | Host port Caddy publishes for HTTPS | `deploy/compose.yaml` | compose |
| `KVZ_SERVER_TZ` | no | `Europe/Prague` | Time zone the containers run in (as `TZ`). Logs and the server clock in the administration use it; quiz times follow the time zone chosen in the global settings | `deploy/compose.yaml` | compose |

### Request limits

Counted per client address and minute (the login has two buckets: per user name and address, and per address across all names); a request over the limit gets 429 with `Retry-After: 60`. Values and counting: [ADR-0030](_architecture/adr/0030-rate-limit-thresholds.md), [ADR-0058](_architecture/adr/0058-rate-limit-buckets.md).

| Variable | Required | Default | Meaning | Read in | Compose |
|---|---|---|---|---|---|
| `KVZ_LOGIN_ATTEMPTS_PER_MINUTE` | no | `5` | Wrong administration logins per client address and user name | `app/settings.py`, `app/api/rate_limit.py` | app |
| `KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE` | no | `30` | Wrong administration logins per client address across all user names | `app/settings.py`, `app/api/rate_limit.py` | app |
| `KVZ_CODE_ATTEMPTS_PER_MINUTE` | no | `10` | Wrong access codes one client address may try | `app/settings.py`, `app/api/rate_limit.py` | app |
| `KVZ_SUBMITS_PER_MINUTE` | no | `120` | Submit requests per client address | `app/settings.py`, `app/api/rate_limit.py` | app |
| `KVZ_STARTS_PER_MINUTE` | no | `300` | Start requests per client address | `app/settings.py`, `app/api/rate_limit.py` | app |
| `KVZ_TRUSTED_PROXIES` | no | `1` | Proxies in front of the application that append the client address to `X-Forwarded-For` (Caddy in Compose, the ingress in Kubernetes); `0` when clients reach the application directly ([ADR-0066](_architecture/adr/0066-single-container-image.md)) | `app/settings.py`, `app/api/rate_limit.py` | no |

The counters live in process memory, so a restart resets them, and the application runs as one
process on purpose: a second worker would count on its own. The client address is the N-th
`X-Forwarded-For` value from the right, N = `KVZ_TRUSTED_PROXIES`: the one the outermost trusted
proxy appended (with one proxy, the one it appended); values further left come from the client or unknown proxies and can be forged. In Compose Caddy
replaces any `X-Forwarded-For` a client sends with the real address, so the default `1` takes it, and
only because the application is reachable through Caddy alone
([ADR-0058](_architecture/adr/0058-rate-limit-buckets.md), [ADR-0066](_architecture/adr/0066-single-container-image.md)).
Behind another proxy in front of Caddy all clients would share the proxy's address.

### Backups

The daily backup is made by the `jobs` service.

| Variable | Required | Default | Meaning | Read in | Compose |
|---|---|---|---|---|---|
| `KVZ_BACKUP_RETENTION_DAYS` | no | `30` | Days a backup is kept before the pass after each backup attempt removes it. The newest backup that still verifies is never removed, even when it is older than this ([ADR-0059](_architecture/adr/0059-backup-and-restore.md)) | `app/settings.py`, `app/domain/management/commands/jobs.py`, `app/domain/management/commands/backup.py` | app |
| `KVZ_BACKUP_PATH` | no | `/data/backups` | Directory of the backups. Compose mounts the `backups` volume there for `jobs` only and does not pass this variable: treat the path as fixed by the image. Set it only outside Compose | `app/settings.py`, `app/domain/backup.py` | no |

### Set by the image, or not for operators

| Variable | Required | Default | Meaning | Read in | Compose |
|---|---|---|---|---|---|
| `KVZ_DB_PATH` | set by the image | `/data/db/kvizotron.sqlite3` | SQLite file on the `db` volume | `Dockerfile`, `app/providers/persistence_sqlite/provider.py` | no |
| `KVZ_MEDIA_PATH` | no | `/data/media` | Stored images on the `media` volume; include it in backups. Compose does not pass it, so the default and the volume agree | `app/settings.py`, `app/providers/media_local/provider.py` | no |
| `KVZ_DEBUG` | no | off | `1` enables Django debug mode and non-secure cookies; for development only, never in production. Compose does not pass it | `app/settings.py` | no |
| `KVZ_PROVIDER_<CAPABILITY>` | no | none | Chooses one provider of an exactly-one capability, for example `KVZ_PROVIDER_AUTH=auth.local`; needed only when several are installed. Rule: [plugin-api.md](plugin-api.md) | `app/kernel/discovery.py` | no |

## Where the settings live

Environment variables hold what belongs to the installation: the domain, the secret, ports, limits
and paths. Everything an admin chooses for quizzes (palette, time zone, data profile, retention
period, branding and so on) is a setting stored in the database. Settings are inherited from global
to quiz to question; a narrower scope needs a written reason ([ADR-0042](_architecture/adr/0042-settings-inherited-and-declared.md)).
Which admin page holds which setting is in [Where things are set](_architecture/modules/api-ui.md#where-things-are-set).

# Deployment & Operations

Decision: [ADR-0015](_architecture/adr/0015-docker-compose-caddy-systemd-alt.md). Architecture view:
[_architecture/architecture.md](_architecture/architecture.md#2-containers-deployment-units).

## Topology

- **Docker Compose** (primary): `caddy` (reverse proxy, automatic HTTPS) + `app` (Django under gunicorn, single
  process) + `jobs` (same image: deletes data past their period and makes the daily backup) + persistent volumes for SQLite, media and backups. Files: `deploy/compose.yaml`, `deploy/Caddyfile`.
- **Single container** (alternative): the `single` target of the same Dockerfile runs migrations, the application and `jobs` in one container, for example one pod in Kubernetes behind an ingress that terminates TLS ([Kubernetes](#kubernetes-single-container), [ADR-0066](_architecture/adr/0066-single-container-image.md)). Documented, not covered by `make smoke`.
- **systemd** (alternative): app as a service behind Caddy, without Docker. Documented only; not tested
  or supported like Compose.
- Runs on the operator's own Linux server and domain.

## Start

```sh
cp deploy/.env.example deploy/.env    # then fill in the values
docker compose -f deploy/compose.yaml up -d --build
```

Caddy and the application refuse request bodies over 16 MiB, or 101 MiB on an import and a public submit (`deploy/Caddyfile`, `app/kernel/middleware.py`, ADR-0066; Caddy sends the application a length even for a chunked body and refuses one over its limit with 413), and the application refuses multipart requests except where a file is expected.

A one-shot `migrate` service applies database migrations before `app` starts; Caddy starts when `app` is
healthy. The application serves its few static files itself, so no collect step is needed. Errors and warnings go to the container log (`docker compose logs app`). Neither gunicorn nor Caddy writes request paths there, and keeping it so protects the tokens in test links ([ADR-0044](_architecture/adr/0044-preview-and-test-links.md)). Caddy accepts up to 101 MB on `/admin/import/*` for ZIP imports and 16 MB elsewhere. Caddy closes its idle connections to the application after 1 second (`keepalive 1s`), because gunicorn closes an idle one after 2 seconds, and a POST sent on a connection closed at that moment was answered 502 ([ADR-0058](_architecture/adr/0058-rate-limit-buckets.md#proxy-keep-alive)). If you start gunicorn with another `--keep-alive`, keep Caddy's value below it. A changed `deploy/Caddyfile` reaches a running proxy only after `docker compose -f deploy/compose.yaml up -d --force-recreate caddy`.

The `jobs` service runs `python manage.py jobs`: one pass at start and then one per hour. A pass runs the retention pass and, when there is no backup for the current local date yet, makes one ([Backup and restore](#backup-and-restore)). It has the same image, volumes and hardening as `app`, plus the `backups` volume, which no other service mounts. A pass deletes the data of runs past their period ([privacy.md](privacy.md#deletion-of-a-runs-data)), and failures appear in its log by run id (`docker compose -f deploy/compose.yaml logs jobs`). To make one pass by hand, or from a host's cron: `docker compose -f deploy/compose.yaml exec jobs python manage.py retention`. Its healthcheck reads the record of the last pass that `jobs` keeps beside the database file (`python -m app.domain.heartbeat check`, no network and no database; the image's own check calls port 8000, which only `app` listens on). It turns unhealthy when no pass is running and the last one finished more than two hours ago, or when a pass has been running for more than an hour (a first pass after a long stop counts from its own start, not from the old finish), or when the `jobs` heartbeat file has not been touched for 45 seconds, so a stuck loop shows in `docker compose ps`, while a long backup does not trip it. The first check runs a minute after the start, so `up --wait` takes about a minute longer than before. A stop (`docker compose stop`) lets a pass that is running finish its current step: `jobs` gets 120 seconds and starts no backup after the signal (the pass is recorded `stopped`), `app` gets 35 seconds, gunicorn's graceful timeout plus five. The Deletion history page shows the time and outcome of the last pass ([ADR-0061](_architecture/adr/0061-heartbeat-and-restore-marker.md)). `jobs` and `app` also touch a small hidden file beside the database while they run, which a restore reads (below); both are removed on a clean stop.

After upgrading to the version with this service, runs already past their period, or past their deadline and unsettled, are held and stay until an admin confirms them on the Deletion history page.

`make smoke` runs the whole topology under a separate project name and removes only that project afterwards. `make load` does the same for the load test ([Release checks](#release-checks-v10)).

Since D5 the application is fit for public deployment, behind Caddy in this topology or behind an ingress as a [single container](#kubernetes-single-container), in one application process. The request limits take the client address that the nearest trusted proxy (Caddy here, an ingress in Kubernetes) wrote into `X-Forwarded-For` and count in the memory of that one process ([ADR-0058](_architecture/adr/0058-rate-limit-buckets.md), [ADR-0066](_architecture/adr/0066-single-container-image.md)). If another proxy sits in front of Caddy, or Docker hides the real address (rootless Docker, a userland proxy), all clients share one address and the limits; `make load` ends with an address probe that shows it.

The administration login has two limits ([ADR-0060](_architecture/adr/0060-login-reservation-and-address-ceiling.md)): 5 wrong logins a minute per user name and address (`KVZ_LOGIN_ATTEMPTS_PER_MINUTE`), and a ceiling of 30 wrong logins a minute per address across all user names (`KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE`). The ceiling is per address, never per account. On a shared address (an office or a school behind one NAT) every administrator there shares the 30, which is far above honest typos, but a spray of guesses from that address blocks all of them from logging in for as long as the spray goes on (a restart clears it), even with the right password, because the check comes before the password is looked at. A restart of the application clears both counters. Raise the ceiling only if you really see that many typos; do not lower the per-name limit below what one person needs.

## Environment variables

Every variable, with its default and whether Compose passes it to the containers, is listed in [configuration.md](configuration.md). `KVZ_DOMAIN` and `KVZ_SECRET_KEY` are required.

## Backup and restore

Decision and rules: [ADR-0059](_architecture/adr/0059-backup-and-restore.md). What a backup holds and how long: [privacy.md](privacy.md#backups).

The `jobs` service makes one backup per local day, the first when it starts, into the `backups` volume (`/data/backups` in the container). A backup is a directory `YYYY-MM-DD` with a copy of the database made with SQLite's backup API, the media files and a manifest (the transient `exports/` and `imports/` directories under the media root, which hold results exports and uploaded imports for at most a day, are not backed up and a restore leaves them where they are); it appears under that name only after it has been verified and written to disk. Media files that did not change are hard-linked to the previous backup (a file damaged there is copied instead), so a backup costs what changed. After every backup attempt, also a failed one, backups older than `KVZ_BACKUP_RETENTION_DAYS` ([configuration.md](configuration.md#backups)) are deleted; the newest backup that verifies always stays. A failed backup shows in the log of `jobs` and as "failed" in the last pass on the Deletion history page. A prune that cannot delete an old backup directory logs only how many stayed; `manage.py backup` then prints the backup, writes that number to stderr and exits non-zero, so run it from a script and check its exit code:

```sh
docker compose -f deploy/compose.yaml logs jobs
docker compose -f deploy/compose.yaml exec jobs ls /data/backups
docker compose -f deploy/compose.yaml exec jobs python manage.py backup    # one backup now, and pruning
```

A manual `manage.py backup` on a date that already has a backup replaces that backup (the new one is verified first). Before an upgrade, copy today's backup directory aside, or make the pre-upgrade backup on the day before, if you want to be able to roll back to it; the daily backup of the next date would otherwise be the first one made by the new version.

A backup on the same machine does not survive losing it. Copy the volume to another machine on a schedule you choose, with a tool that keeps hard links (otherwise every backup becomes a full copy), for example as root on the host `rsync -aH "$(docker volume inspect kvizotron_backups --format '{{ .Mountpoint }}')/" backuphost:/srv/kvizotron-backups/`. Backups are not encrypted and hold personal data: protect the copy as you protect the volume. The copy is outside the application's retention: nothing prunes it for you, so delete its old backups yourself within the same number of days (`KVZ_BACKUP_RETENTION_DAYS`). Adding `--delete` to `rsync` makes the copy mirror what the volume has pruned, but it also mirrors a deletion made by accident, so use it only when you keep another copy.

If a provider is switched through `KVZ_PROVIDER_*` ([plugin-api.md](plugin-api.md)), the rows of the old provider remain in the database's migration table and every backup fails the check "migrations this version does not know" until the old provider is installed again or those rows are removed. The `jobs` log shows it.

### Restore

Restoring replaces the database and the media with a backup. Stop everything that uses them first, restore, and start again:

```sh
docker compose -f deploy/compose.yaml stop caddy app jobs
docker compose -f deploy/compose.yaml run --rm --no-deps jobs python manage.py restore latest
docker compose -f deploy/compose.yaml up -d
```

`latest` is the newest complete backup; name a date (`restore 2026-11-09`) for another. The command:

- verifies the backup first and stops if it is damaged. `latest` never falls back to an older day: when it says that the backup cannot be restored, list the dates with `docker compose -f deploy/compose.yaml run --rm --no-deps jobs ls /data/backups` (the `exec` form above needs `jobs` running) and name one;
- refuses a backup from an older schema (use the version of the application that made it, or migrate it deliberately);
- refuses while `app` or `jobs` runs. Each touches a hidden file beside the database while it serves or loops; the restore refuses while either file is younger than 60 seconds, names the service and says how many seconds are left until it counts as stopped. Stop `caddy`, `app` and `jobs` first (`docker compose -f deploy/compose.yaml ps` shows what runs); a service that was killed leaves its file, so a restore started right after `stop` may have to wait up to a minute: run it again;
- refuses while a connection to the database is open at that very moment, which a request or a pass in flight would hold. If all three services are stopped and the refusal says that the `-wal` and `-shm` files remain beside the database, do not delete them by hand. Open the database once and close it, which folds the log into it and removes both files, and run the restore again: `docker compose -f deploy/compose.yaml run --rm --no-deps jobs python -c "import sqlite3; c = sqlite3.connect('/data/db/kvizotron.sqlite3'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"`;
- refuses while an earlier restore did not finish (see below);
- copies the current database and media to `pre-restore-<time>` in the backups volume before it replaces anything and writes the marker `.restoring` there (it removes the marker when the restore ends, or when it has put the previous data back), restores media as copies, puts the previous data back when something fails, checks the result and prints what it restored and where the previous data is. Run through the `jobs` service it runs as uid 1000, so the restored files belong to the application's user;
- leaves `pre-restore-*` to the normal pruning: it is deleted after `KVZ_BACKUP_RETENTION_DAYS` days like a backup, except a directory that still holds the marker, which is never deleted.

A restore brings back what the backup held. Runs past their period are deleted again by the next hourly pass, except runs that the backup still holds as held ([ADR-0056](_architecture/adr/0056-retention-job-summary-held-runs.md)), which an admin confirms on the Deletion history page. An erasure request, a "Delete data now" or any other deletion made after the backup date must be repeated by you ([privacy.md](privacy.md#backups)).

**A restore that did not finish.** When the host lost power or the command was killed, the database and media may be partly the backup's, and the next `restore` refuses and names a `pre-restore-<time>` directory: the one that holds the marker `.restoring`, with the data from before that restore. Look at what the last restore printed:

- If it printed "Restored", or a warning that the marker could not be removed, the restore itself finished and only the marker was left (the file could not be deleted). Nothing is wrong with the data: remove the marker and run the next restore.
- If it did not print "Restored" (it was killed, or it failed), and the data are not what you want, put the named directory back, which replaces what is in the volumes now, and then remove its marker. If the put-back itself succeeded but its marker could not be removed, the marker stays without a warning; the next restore refuses, and putting the directory back again is harmless because the data in the volumes are already the previous ones. Do the steps with `caddy`, `app` and `jobs` stopped.

The refusal names every directory that holds a marker; repeat the step for each. Remove the marker, with the directory name from the refusal:

```sh
docker compose -f deploy/compose.yaml run --rm --no-deps jobs rm /data/backups/pre-restore-<time>/.restoring
```

Put the directory back (the last step is the marker):

```sh
docker compose -f deploy/compose.yaml run --rm --no-deps jobs sh -c 'ls -d /data/backups/pre-restore-*'
docker compose -f deploy/compose.yaml run --rm --no-deps jobs sh -c '
  from=/data/backups/pre-restore-<time>
  [ -f "$from/kvizotron.sqlite3" ] &&
  rm -f /data/db/kvizotron.sqlite3 /data/db/kvizotron.sqlite3-wal /data/db/kvizotron.sqlite3-shm &&
  cp -p "$from"/kvizotron.sqlite3* /data/db/ &&
  find /data/media -mindepth 1 -delete &&
  if [ -d "$from/media" ]; then cp -a "$from/media/." /data/media/; fi &&
  rm -f "$from/.restoring"'
docker compose -f deploy/compose.yaml up -d
```

**The restore drill.** A backup counts only when it has been restored. `make load` does it automatically: it makes a backup of a stack full of attempts and photos, changes the live data, restores, and compares rows and photo checksums with those before. On your own installation, do it once after setting up and after every upgrade: make a backup (`manage.py backup`, while `jobs` runs), stop `caddy app jobs`, run `restore latest`, start the stack and check that the quizzes, runs and photos are the ones you expect. Nothing is lost by it, because the data it replaced stay in `pre-restore-<time>`.

## Modules

`manage.py modules` lists installed modules, enables or disables a plugin and runs the startup
verification:

```sh
docker compose -f deploy/compose.yaml run --rm app python manage.py modules list
docker compose -f deploy/compose.yaml run --rm app python manage.py modules disable <module id>
```

`run` also works while the application cannot start. It refuses to start while migrations are unapplied,
including after a new module is installed, and while an enabled module depends on a disabled one. Rules: [modules/kernel.md](_architecture/modules/kernel.md#module-installation-and-activation).

## Kubernetes (single container)

The image's `single` target runs everything in one container ([ADR-0066](_architecture/adr/0066-single-container-image.md)):

```sh
docker build --target single -t kvizotron:single .
```

Its command, `python manage.py serve`, applies the migrations, then runs gunicorn (one worker) and `jobs` side by side. Before the migrations it creates the directory of the database, since a fresh volume does not show the image's own. A stop sends SIGTERM to both and, counted from that moment, waits up to 30 s for gunicorn and 115 s for a backup in progress; a child that ends ends the container (a signal that killed it gives 128 + its number), so the orchestrator restarts it whole. gunicorn keeps idle connections for 75 s, longer than an ingress keeps them (ingress-nginx: 60 s), or a POST sent on a connection gunicorn just closed would get 502. The image's health check calls `/healthz` and `python -m app.domain.heartbeat check`, which passes before the first pass of `jobs` and fails when its heartbeat stops.

What Caddy does in Compose is split between the ingress and the application:

| Duty | In Kubernetes |
|---|---|
| TLS and certificates | The ingress (with cert-manager or your own certificate); it must send `X-Forwarded-Proto: https` |
| HSTS, six months | The application, on HTTPS requests |
| Body ceiling: 16 MiB, 101 MiB on `/admin/import/…` and `/a/<id>/submit` | The application (413), also for Caddy's limits in Compose; a body that reaches the application without `Content-Length` (chunked) is refused with 411; browsers always send a length, and in Compose Caddy forwards one. Set the ingress at least as high, for example `nginx.ingress.kubernetes.io/proxy-body-size: 101m` |
| Client address for the request limits | The ingress appends it to `X-Forwarded-For`; `KVZ_TRUSTED_PROXIES` counts the proxies that do so (default 1, the ingress). With a cloud load balancer in front, make the ingress see the real address (`externalTrafficPolicy: Local` or the PROXY protocol), or all clients share one limit |
| Slow clients and idle connections | The ingress; never expose the container's port directly. A NetworkPolicy that lets only the ingress controller reach port 8000 keeps other pods from sending their own `X-Forwarded-For` |

Constraints of the pod:

- **One replica** and `strategy: Recreate`: SQLite and the in-memory limits allow one process, and a rolling update would briefly run two pods on one database.
- **A `ReadWriteOnce` volume** on local or block storage (not NFS) at `/data` for `db` and `media`, and **a second one at `/data/backups`**, so that losing one volume does not take the data and its backups together; give it another storage class or snapshots if you can, and copy the backups out of the cluster as well (for example a CronJob with `rsync` or `kubectl cp`). The image runs as uid 1000; set `fsGroup: 1000`.
- **`terminationGracePeriodSeconds: 120`** at least, so a backup in progress can finish its step.
- **Probes:** readiness asks `/healthz`; liveness asks `/healthz` and `python -m app.domain.heartbeat check --alive`, which fails only when the `jobs` loop stopped beating. The full `check` (a pass running over an hour, none finished for two) is the status Compose shows, and as a liveness probe it would restart the pod in the middle of a long backup ([ADR-0066](_architecture/adr/0066-single-container-image.md)).
- **Secret** `KVZ_SECRET_KEY` (at least 32 characters), created outside the repository: `kubectl create secret generic kvizotron --from-literal=secret-key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"`. Other variables as in [configuration.md](configuration.md).
- **NetworkPolicy:** only the ingress controller may reach port 8000. A pod that reaches it directly can write its own `X-Forwarded-For` and `X-Forwarded-Proto`, and then the request limits, the login limit among them, no longer hold. The policy needs a network plugin that enforces it.
- **Client address:** behind an L4 load balancer, make the ingress see the real address (`externalTrafficPolicy: Local` on its Service, or the PROXY protocol) and keep `KVZ_TRUSTED_PROXIES` at 1; an L7 load balancer that appends to `X-Forwarded-For` makes it 2. Otherwise all clients share one limit.

An example, to adapt (names, namespace of the ingress controller, storage class, ingress class, host, resources):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: {name: kvizotron}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector: {matchLabels: {app: kvizotron}}
  template:
    metadata: {labels: {app: kvizotron}}
    spec:
      terminationGracePeriodSeconds: 120
      automountServiceAccountToken: false  # the application never calls the Kubernetes API
      securityContext:
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        runAsNonRoot: true
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: kvizotron
          image: registry.example.com/kvizotron:single
          ports: [{containerPort: 8000}]
          env:
            - {name: KVZ_DOMAIN, value: kviz.example.com}
            - name: KVZ_SECRET_KEY
              valueFrom: {secretKeyRef: {name: kvizotron, key: secret-key}}
          securityContext:
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
          resources:  # about 50 participants; a backup and an export run in the same container
            requests: {cpu: 250m, memory: 512Mi}
            limits: {memory: 1Gi}
          volumeMounts:
            - {name: data, mountPath: /data}
            - {name: backups, mountPath: /data/backups}
          # The kubelet sends the pod IP as Host, which ALLOWED_HOSTS refuses; localhost is allowed.
          startupProbe:
            httpGet: {path: /healthz, port: 8000, httpHeaders: [{name: Host, value: localhost}]}
            failureThreshold: 30
            periodSeconds: 5
          readinessProbe:
            httpGet: {path: /healthz, port: 8000, httpHeaders: [{name: Host, value: localhost}]}
            periodSeconds: 10
          livenessProbe:  # the application answers and the jobs loop beats; never the pass age
            exec:
              command:
                - sh
                - -c
                - >-
                  python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)"
                  && python -m app.domain.heartbeat check --alive
            periodSeconds: 60
            timeoutSeconds: 10
      volumes:
        - name: data
          persistentVolumeClaim: {claimName: kvizotron-data}
        - name: backups
          persistentVolumeClaim: {claimName: kvizotron-backups}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: kvizotron-data}
spec:
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: 10Gi}}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: kvizotron-backups}
spec:
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: 20Gi}}
---
apiVersion: v1
kind: Service
metadata: {name: kvizotron}
spec:
  selector: {app: kvizotron}
  ports: [{port: 80, targetPort: 8000}]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: kvizotron}
spec:
  podSelector: {matchLabels: {app: kvizotron}}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: ingress-nginx}}
          podSelector: {matchLabels: {app.kubernetes.io/name: ingress-nginx}}
      ports: [{port: 8000}]
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: kvizotron
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: 101m
spec:
  ingressClassName: nginx
  tls: [{hosts: [kviz.example.com], secretName: kvizotron-tls}]
  rules:
    - host: kviz.example.com
      http:
        paths:
          - {path: /, pathType: Prefix, backend: {service: {name: kvizotron, port: {number: 80}}}}
```

The first administrator: `kubectl exec -it deploy/kvizotron -- python manage.py init_admin <login>`. A restore needs the application stopped: scale to 0, wait a minute (the heartbeat of the stopped application must be older than 60 s, see [Restore](#restore)), run `python manage.py restore <date|latest>` in a one-off pod with the same volumes and image, then scale back to 1.

## Constraints

- Database volume constraints (local disk only, WAL, single writer): see
  [persistence-sqlite](_architecture/providers/persistence-sqlite.md).

### HSTS

The application sends `Strict-Transport-Security: max-age=15552000` (six months) on HTTPS requests,
without `includeSubDomains` and without `preload`; in Compose Caddy replaces it with the same value. Browsers ignore the header for an IP address and over a certificate they do
not trust (RFC 6797, section 8.1), so a LAN deployment reached by IP address is unaffected. A LAN
host name with a certificate from a local authority that browsers trust is different: after one visit
the browser refuses certificate exceptions for that name for six months, so a broken or expired
certificate cannot be clicked through. Serve such a deployment only with a certificate you can keep
valid.

## Minimum operational elements

- Docker healthcheck on `/healthz`, backed by `PersistenceProvider.healthcheck()`.
- Clear logs without answers or PII.
- Configuration via environment variables and secrets (never committed). `KVZ_SECRET_KEY` signs
  attempt tokens and the session hash. Change it only when no run is open: it invalidates attempts in progress
  and logs admins out ([ADR-0024](_architecture/adr/0024-attempt-token-signing.md)). It also keys the e-mail fingerprints of erasure requests: after a change, earlier fingerprints can no longer be verified by retyping the address, while the rest of those records stays ([ADR-0056](_architecture/adr/0056-retention-job-summary-held-runs.md)).
- SQL and asset backups with **verified restore**, made with SQLite's backup mechanism, never a plain
  file copy; backup retention limited so that deleted personal
  data are not restored without reason ([privacy.md](privacy.md#backups)); procedure above. Restored files **MUST** be owned by uid 1000,
  the application's user; otherwise `migrate` fails with `unable to open database file` and `app` does not start. `manage.py restore` does it when run as root and through the `jobs` service it already is that user.
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
- Scheduled jobs: the `jobs` service with Compose. Under systemd, run `manage.py jobs` as a second service, or `manage.py retention` and `manage.py backup` from timers.

## Release checks (v1.0)

Every item has a command; all of them pass before a release is tagged. Ports are for a machine where another stack already runs.

| Check | Command | What it proves |
|---|---|---|
| Lint, tests, secrets, technical-debt list | `make quality` | Includes the acceptance criteria named by tests (`tests/test_docs.py`) and the configuration reference (`tests/test_configuration_docs.py`, [AC-138](_architecture/acceptance-criteria.md)) |
| Deployment starts and answers | `make smoke` (`SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke` beside another stack) | The compose topology: required variables, health through Caddy, headers, a first login, a play-through, the first backup, a manual backup and a restore |
| 50 participants with photos, backup during the burst, restore, address probe | `make load` (`LOAD_HTTP_PORT`, `LOAD_HTTPS_PORT` change its ports); takes minutes and needs Docker | [AC-139](_architecture/acceptance-criteria.md): it must end with `LOAD OK`, not `LOAD OK (address not measured)`, which means no LAN address was found to probe |
| Restore on the installation | The restore drill above | Your backups restore on your volumes |
| Pages in a browser | The project skill `kvizotron-browser-walkthrough` (stack `kvizotron-browser`) | What a person sees: the 429 pages, public pages, footer, headers |

`make load` is not part of `make quality`, because no CI runs it. The same 50-participant scenario also runs on every `make test` as a thread test on a file database (`tests/integration/test_concurrent_submissions.py`), without Docker.

Limits of `make load`: its address probe cannot tell 127.0.0.1 from 127.0.0.2, because Docker's proxy serves the published ports and every loopback source reaches Caddy as one address (measured; a LAN source is counted apart), so only a LAN source proves that addresses are counted apart, and a quiz with a photo question cannot show the answer after each question (the application forbids the combination), so the load runs one quiz with photos and another with reveal after each question ([TD-086](_architecture/TECH_DEBT.md)).

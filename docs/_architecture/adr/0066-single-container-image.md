---
status: accepted
date: 2026-11-16
---

# ADR-0066: A single-container image beside the Compose deployment

## Context and Problem Statement

The supported deployment is Docker Compose with four services from one image: `migrate`, `app`, `jobs` and Caddy ([ADR-0015](0015-docker-compose-caddy-systemd-alt.md)). An operator who runs Kubernetes wants everything in one container behind the cluster's ingress, which terminates TLS. Caddy does more than TLS: it sends HSTS, caps the request body, writes the client address the request limits trust and shields the application from slow clients. Without Caddy those duties need a new owner.

## Decision Drivers

* Everything the application needs runs in one container; Compose stays as it is
* No duty of Caddy silently disappears: HSTS, the body ceiling and a client address that cannot be forged
* One application process, as SQLite and the in-memory request limits require ([ADR-0005](0005-sqlite-wal-sqlalchemy-alembic-behind-persistence-provider.md), [ADR-0058](0058-rate-limit-buckets.md))
* A container that is half running is restarted as a whole

## Considered Options

* (a) A new image with Caddy and a process manager inside
* (b) A `single` target of the same Dockerfile: a small supervisor (`manage.py serve`) runs the migrations, then gunicorn and `jobs`; the application takes over HSTS and the body ceiling; the client address comes from a configured number of trusted proxies
* (c) Several containers in one Kubernetes pod (init container, `app`, `jobs`)

## Decision Outcome

Chosen option: (b). Option (a) duplicates TLS that the ingress already does and adds a dependency; option (c) was declined by the user, who wants one container.

* `docker build --target single` gives the image; its command is `python manage.py serve`. It runs `migrate`, then gunicorn (one worker, as in Compose) and `jobs`. It creates the directory of the database first (a fresh volume hides the image's). SIGTERM goes to both, and counted from that one moment gunicorn gets 30 s and `jobs` 115 s before a kill, so the pod's `terminationGracePeriodSeconds` must be at least 120; a stop during the migrations starts nothing. A child that ends ends the container with its code (1 if it ended with 0, 128 + N for signal N); a child that cannot start stops the others. gunicorn keeps idle connections 75 s (`--keep-alive`), longer than an ingress keeps them, where Compose's Caddy closes its own after 1 s instead. Both images start gunicorn with `--no-control-socket`: gunicorn 26 would open its control socket under `$HOME`, and the image user has no home directory. Its health check calls `/healthz` and `python -m app.domain.heartbeat check`.
* The default build (no target) stays the image Compose runs, and Compose keeps Caddy.
* The application sends `Strict-Transport-Security: max-age=15552000` on HTTPS requests (as Caddy does, AC-132) and refuses a body over 16 MiB, or 101 MiB on `/admin/import/…` and `/a/<id>/submit`, by its declared length (413), a body that reaches it without a length (411; in Compose Caddy forwards a length and refuses an oversized chunked body itself, which `make smoke` checks) and a malformed length (400), before anything reads it. Caddy keeps the same limits in Compose (in MiB, a test compares them). The check runs after the middleware that adds security headers, so a refusal carries them.
* The client address of the request limits is the N-th `X-Forwarded-For` value from the right, N = `KVZ_TRUSTED_PROXIES` (default 1, the number of proxies in front of the application that append to the header): the value the outermost trusted proxy appended; 0 means the connection address. Behind an L4 load balancer the ingress must see the real address (`externalTrafficPolicy: Local` or the PROXY protocol) and N stays 1; an L7 load balancer that appends to the header makes N 2. Values further left can be forged by the client. This replaces "the first value" of [ADR-0058](0058-rate-limit-buckets.md); in Compose Caddy writes a single value, so nothing changes there.

### Consequences

* Good, because a Kubernetes or other single-container deployment keeps HSTS, the body ceiling and limits that a client cannot dodge.
* Good, because Compose, `make smoke` and `make load` are unchanged.
* Bad, because the application now holds limits Caddy also holds; the values must change together (`deploy/Caddyfile`, `app/kernel/middleware.py`).
* Bad, because the single container is not covered by `make smoke`; it is documented in [deployment.md](../../deployment.md#kubernetes-single-container), not tested end to end.
* Neutral, because a health check means more in Kubernetes than in Compose: a liveness probe restarts the pod, so it asks only `heartbeat check --alive` (the `jobs` loop beats), never the age of a pass, or a long backup would be killed in the middle; the full `check` stays the status Compose and the image show.
* Neutral, because the example keeps the backups on a second volume at `/data/backups` (Compose has a separate `backups` volume); with one volume a lost volume would take the data and the backups together.
* Bad, because the kernel's body limit names two product addresses, as `UPLOAD_ROUTE` already does; tests keep them equal to Caddy's `@large` paths.
* Neutral, because a cloud load balancer in front of the ingress hides the client address unless the ingress is told the real one; the operator sets `KVZ_TRUSTED_PROXIES` to match.

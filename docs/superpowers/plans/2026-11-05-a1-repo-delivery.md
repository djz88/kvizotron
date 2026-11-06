# A1 Repo & Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Working `make` targets, CI calling `make quality`, and a Docker Compose + Caddy deployment serving a minimal Django project with a health check.

**Architecture:** A minimal Django project with no kernel yet and no installed apps, so that no database tables exist before the custom user model arrives in A3. Delivery runs one gunicorn process behind Caddy. CI only calls `make`.

**Tech Stack:** Python 3.15, Django 6.1.3, gunicorn 26.2.0, uv, ruff 0.17.3, mypy 2.4.1, pytest 9.2.0, pytest-django 4.14.0, pre-commit 4.7.0 + gitleaks, Docker Compose, Caddy 2.11.

**Spec:** `docs/_architecture/roadmap.md` (A1), `docs/deployment.md`, ADR-0015, ADR-0022, ADR-0036, TD-006, TD-007.

## Global Constraints

- Python pinned to 3.15 in `pyproject.toml`, the Dockerfile and CI (ADR-0022); `requires-python = ">=3.15,<3.16"`.
- Dependencies pinned exactly, with `uv.lock` committed. Only what A1 uses: runtime `django`, `gunicorn`; dev `ruff`, `mypy`, `pytest`, `pytest-django`.
- `[tool.uv] required-version = ">=0.13"`: uv 0.10 only offers Python 3.15 alpha.
- Images pinned by digest: `python:3.15-slim@sha256:e97b88e416c3c01eb427b21fd8cd3ebf006e6ee38afcfcc3cae1c54ee2ab0a75`, `caddy:2-alpine@sha256:f6228111e5fafa1a5238258d0858e103f10599b8d1659a146e7726681a002bb9`.
- Actions pinned by SHA: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1), `astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2` (v10.3.3).
- Gunicorn: `--workers 1 --threads 8` (ADR-0036).
- `INSTALLED_APPS = []` in A1. Do not install `django.contrib.auth`: the user model must be fixed before its first migration (ADR-0036).
- No secret has a default value. Tests use an obviously fake key.
- Environment names: `KVZ_SECRET_KEY`, `KVZ_DOMAIN`, `KVZ_DB_PATH`, `KVZ_DEBUG`, `KVZ_HTTP_PORT`, `KVZ_HTTPS_PORT`.
- `docs/` stays in English. `CLAUDE.md`, root `README.md` and Makefile comments stay in Czech.

## Review Focus

- `KVZ_SECRET_KEY` missing or empty: the app refuses to start and names the variable. Test in Task 1.
- Database unreadable: `/healthz` returns 503 with no path or exception text. Test in Task 1.
- Docker volume owned by root while the app runs as non-root: migration and health check must still work. Covered by the smoke test in Task 3.
- `KVZ_DOMAIN` or `KVZ_SECRET_KEY` unset in Compose: `docker compose config` fails naming the variable, instead of starting with empty values. Test in Task 3.
- Plain HTTP request to the deployment: redirected to HTTPS, with no app response over HTTP. Test in Task 3.

---

### Task 1: Django project, health check, `make setup/lint/test`

**Files:**
- Create: `pyproject.toml`, `uv.lock`, `manage.py`, `app/__init__.py`, `app/settings.py`, `app/urls.py`, `app/wsgi.py`, `app/api/__init__.py`, `app/api/health.py`, `tests/__init__.py`, `tests/settings.py`, `tests/test_health.py`, `tests/test_settings.py`
- Modify: `Makefile`, `.gitignore` (nothing to add unless the run shows otherwise)

**Interfaces:**
- Produces: `app.settings` reading env; `GET /healthz`; `make setup`, `make lint`, `make lint fix`, `make test`.

- [x] **Step 1: Write `pyproject.toml` and lock.** Package is not installed (`[tool.uv] package = false`). Ruff `target-version = "py315"`, rules `E,F,I,UP,B,S` with `S101` ignored in `tests/`. Mypy on `app` with `ignore_missing_imports = true`. Pytest `DJANGO_SETTINGS_MODULE = "tests.settings"`. Run `uv lock`.

- [x] **Step 2: Write failing tests.**

`tests/settings.py` sets `os.environ.setdefault("KVZ_SECRET_KEY", "test-only-not-a-secret")` and `KVZ_DOMAIN=testserver`, `KVZ_DB_PATH=":memory:"`, then `from app.settings import *`.

```python
# tests/test_health.py
def test_healthz_ok(client, db):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}

def test_healthz_db_failure_is_503_without_details(client, monkeypatch):
    # connection.cursor raises OperationalError("/secret/path")
    r = client.get("/healthz")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}
    assert b"secret" not in r.content

# tests/test_settings.py, importing app.settings in a subprocess
def test_missing_secret_key_aborts_and_names_variable(): ...  # exit != 0, "KVZ_SECRET_KEY" in stderr
def test_empty_secret_key_aborts(): ...
def test_production_cookies_secure_and_debug_off(): ...       # DEBUG False, both cookie flags True
```

- [x] **Step 3: Run `uv run pytest`.** Expected: FAIL, `app.settings` does not exist.

- [x] **Step 4: Implement `app/settings.py`, `app/urls.py`, `app/wsgi.py`, `manage.py`, `app/api/health.py`.**
  - `SECRET_KEY` from `KVZ_SECRET_KEY`; missing or empty raises `ImproperlyConfigured` naming the variable.
  - `DEBUG` true only for `KVZ_DEBUG == "1"`. `ALLOWED_HOSTS = [KVZ_DOMAIN, "localhost"]`; `CSRF_TRUSTED_ORIGINS = ["https://" + KVZ_DOMAIN]`.
  - `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`, `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE = not DEBUG`.
  - SQLite at `KVZ_DB_PATH`, `OPTIONS` with `transaction_mode: "IMMEDIATE"`, `timeout: 20`, `init_command` for WAL and `synchronous=NORMAL`.
  - `TEMPLATES` with the Jinja2 backend is deferred to A4; `TEMPLATES = []`.
  - `health(request) -> JsonResponse`: `select 1`; `django.db.Error` gives 503 `{"status": "unavailable"}` and logs the exception type only.

- [x] **Step 5: Implement Makefile targets.** `setup: uv sync --frozen`; `lint: uv run ruff check $(LINT_FIX) . && uv run ruff format $(if $(LINT_FIX),,--check) . && uv run mypy app`; `test: uv run pytest`.

- [x] **Step 6: Verify on Python 3.15 in a container**, because the local uv may be older: `docker run` with `python:3.15-slim`, `pip install uv`, `make setup lint test`. Expected: all pass, `Python 3.15.2`.

- [x] **Step 7: Commit.**

### Task 2: `make quality` with gitleaks

**Files:**
- Modify: `Makefile`, `docs/_architecture/TECH_DEBT.md`, `docs/_architecture/adr/0022-python-version.md`, `CLAUDE.md`, `README.md`

- [x] **Step 1: Add target `secrets`:** `uvx --python 3.14 pre-commit@4.7.0 run --all-files`, and make `quality: lint test secrets`. It runs on 3.14 because pre-commit needs PyYAML, which has no 3.15 wheel; add a one-line comment saying so.

- [x] **Step 2: Verify the gate fails on a planted secret.** Add a fake AWS-style key to an untracked scratch file with `git add -N`, run `make secrets`, expect failure; remove the file. Then `make quality` passes.

- [x] **Step 3: Update docs.** Move TD-006 to RESOLVED with today's date. Record in ADR-0022 Confirmation that the pinned A1 dependencies install and pass tests on 3.15.2, and that dependencies of later milestones are re-verified as they are added. Update `CLAUDE.md` Příkazy and `README.md` Vývoj.

- [x] **Step 4: Commit.**

### Task 3: Docker image, Compose, Caddy, smoke test

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `deploy/compose.yaml`, `deploy/Caddyfile`, `deploy/.env.example`, `deploy/smoke.sh`
- Modify: `Makefile`, `docs/deployment.md`, `README.md`

**Interfaces:**
- Consumes: `/healthz` and env names from Task 1.
- Produces: `make smoke`, used by CI in Task 4.

- [x] **Step 1: Write `deploy/smoke.sh` first.** It uses a throwaway project name, `KVZ_DOMAIN=localhost`, a key generated at run time, and high ports. It asserts:
  1. Compose without `KVZ_SECRET_KEY` fails and names it; the same for `KVZ_DOMAIN`.
  2. `up --wait` succeeds.
  3. `curl -k https://localhost:$PORT/healthz` returns 200 `{"status": "ok"}`.
  4. Plain HTTP returns a redirect to HTTPS.
  5. A request with a foreign `Host` returns 400 from Django or no site from Caddy, never 200.
  6. The app process is not root (`id -u` != 0).
  7. The SQLite file exists on the volume and `PRAGMA journal_mode` is `wal`.
  It always runs `down -v` at exit, and only for its own project name.

- [x] **Step 2: Run it.** Expected: FAIL, no compose file.

- [x] **Step 3: Write the `Dockerfile`.** Pinned base image; install pinned uv with pip; `uv sync --frozen --no-dev`; user `kvizotron` (uid 1000); create `/data/db` and `/data/media` owned by it, so named volumes inherit the ownership; `ENV KVZ_DB_PATH=/data/db/kvizotron.sqlite3`; `HEALTHCHECK` with Python `urllib` against `http://localhost:8000/healthz`; `CMD` gunicorn with the constraints above, bound to `0.0.0.0:8000`.

- [x] **Step 4: Write `deploy/compose.yaml`.** Services: `migrate` (one-shot `manage.py migrate`), `app` (`depends_on` migrate `service_completed_successfully`, `expose: 8000`), `caddy` (ports `${KVZ_HTTP_PORT:-80}:80`, `${KVZ_HTTPS_PORT:-443}:443`, `depends_on` app `service_healthy`). Volumes `db`, `media`, `caddy_data`, `caddy_config`. Required variables use `${VAR:?message}`. `security_opt: no-new-privileges:true` on all services; `restart: unless-stopped` on app and caddy.

- [x] **Step 5: Write `deploy/Caddyfile`** (`{$KVZ_DOMAIN} { reverse_proxy app:8000 }`) and `deploy/.env.example` with empty values and a comment on how to generate the key. Add `make smoke`.

- [x] **Step 6: Run `make smoke`.** Expected: every assertion passes.

- [x] **Step 7: Update `docs/deployment.md`** with the environment variables and start commands, replacing the "defined in Stage A/D" note for the parts now known; update the root `README.md` installation section.

- [x] **Step 8: Commit.**

### Task 4: CI

**Files:**
- Create: `.github/workflows/quality.yml`
- Modify: `docs/_architecture/TECH_DEBT.md`, `CLAUDE.md`

- [x] **Step 1: Write the workflow.** Triggers: `push`, `pull_request`. `permissions: contents: read`. Job `quality`: checkout with `persist-credentials: false`, setup-uv, `make setup`, `make quality`. Job `smoke`: checkout, `make smoke`. Steps contain no commands other than `make`.

- [x] **Step 2: Lint it:** `docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:latest`. Expected: no findings.

- [x] **Step 3: Simulate the quality job** in a clean `python:3.15-slim` container from a fresh clone of the working tree. Expected: `make setup quality` passes.

- [x] **Step 4: Update docs.** Move TD-007 to RESOLVED and add a new open item: CI has not run on GitHub because the repository has no remote yet. Update `CLAUDE.md` so it no longer says the code does not exist.

- [x] **Step 5: Commit.**

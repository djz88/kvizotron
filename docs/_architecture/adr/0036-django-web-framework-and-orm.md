---
status: accepted
date: 2026-11-05
---

# ADR-0036: Django as web framework and ORM

## Context and Problem Statement

[ADR-0003](0003-python-fastapi-jinja-htmx.md) and [ADR-0005](0005-sqlite-wal-sqlalchemy-alembic-behind-persistence-provider.md)
came from the original spec and chose FastAPI, SQLAlchemy and Alembic. Kvízotron is mostly
server-rendered pages, forms and an admin area, so the project would write sessions, CSRF protection,
per-module migrations, locale handling and management commands itself. No code exists yet, so changing
the choice costs only documentation.

## Decision Drivers

* Less own code in security-sensitive areas (login, sessions, CSRF)
* Modules with their own tables, migrations, templates and routes
* Replaceable authentication and database without changing the kernel
* Simple operation on one server

## Considered Options

* Django replacing FastAPI, SQLAlchemy and Alembic
* FastAPI + SQLAlchemy + Alembic (ADR-0003, ADR-0005)
* Django next to FastAPI, Django for the admin area only

## Decision Outcome

Chosen option: "Django replacing FastAPI, SQLAlchemy and Alembic", because it supplies what the project
would otherwise write, and a Django app already is a module with its own models, migrations, templates,
static files, routes and commands.

Rules:

* **Kept from ADR-0003 and ADR-0005:** Python ([ADR-0022](0022-python-version.md)), server-rendered
  Jinja2, HTMX, small vanilla JavaScript without a build step, Pydantic for contracts and for validating
  JSON input, SQLite in WAL mode on a local volume.
* **Templates:** Django's Jinja2 template backend, not the Django template language.
* **Server:** gunicorn with one worker process and several threads. SQLite and in-process rate limits
  ([ADR-0030](0030-rate-limit-thresholds.md)) depend on a single process.
* **JSON endpoints:** plain Django views with Pydantic models; no API framework, because the JSON surface
  is small and needs no generated documentation.
* **Admin UI:** own pages under `/admin/`. `django.contrib.admin` is not installed, because the quiz
  editor and the draw need their own screens.
* **Sessions:** Django database sessions. A password change invalidates that account's sessions through
  Django's session hash.
* **Attempt token:** `django.core.signing` (HMAC) with `SECRET_KEY` and a dedicated salt. It replaces
  itsdangerous in [ADR-0024](0024-attempt-token-signing.md); the other rules of that ADR stay.
* **Data access:** domain services and modules use Django ORM models directly, without a repository
  layer. `PersistenceProvider` supplies database settings and a health check
  ([../providers/persistence-sqlite.md](../providers/persistence-sqlite.md)).
* **Events:** kernel events ([ADR-0016](0016-in-process-events-no-broker.md)). Modules do not connect
  Django signals, because kernel events can skip disabled modules.
* **Custom user model:** owned by the kernel and fixed from the first migration, so auth providers share
  one table.

Module discovery, the registry and the manifests from [ADR-0004](0004-entry-points-typed-registry-pydantic.md)
and [ADR-0021](0021-plugin-manifest-and-versioning.md) stay; entry points feed `INSTALLED_APPS` at startup.

### Consequences

* Good, because login, sessions, CSRF, password hashing, migrations, i18n and CLI commands come from one maintained framework
* Good, because each module has native migrations, without Alembic branches
* Good, because a different relational database needs only a Django backend, not a new data layer
* Bad, because the database can be replaced only by a relational one with a Django backend
* Bad, because modules are tied to the Django ORM; replacing it would mean rewriting them
* Bad, because the session key is stored unhashed, so someone who can read the database could use an active admin session; such a person can already read all the data
* Bad, because uninstalling a package leaves its tables behind, and their foreign keys can block deletes ([kernel rules](../modules/kernel.md#module-installation-and-activation))
* Bad, because Django's system checks do not query the database at startup, so the kernel needs its own startup verification

### Confirmation

A throwaway spike on Python 3.15.2 and Django 6.1.3 (2026-11-05) installed a question-type module as a
separate package with its own model, migration, route, Jinja2 template and static file, with no change
to core files. Also confirmed: runtime enable/disable, a refused disable while an active quiz uses the
module, startup abort on an invalid manifest, incompatible version, missing dependency or cycle, auth
provider swap on restart, and WAL mode with `IMMEDIATE` transactions under 50 threads.

Not confirmed by the spike: the admin editor part of [AC-01](../acceptance-criteria.md), per-quiz
activation, and real load ([AC-15](../acceptance-criteria.md)). These remain Stage A–D work.

## More Information

Supersedes [ADR-0003](0003-python-fastapi-jinja-htmx.md) and
[ADR-0005](0005-sqlite-wal-sqlalchemy-alembic-behind-persistence-provider.md). Module kinds:
[ADR-0037](0037-providers-and-plugins.md).

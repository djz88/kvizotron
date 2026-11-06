# Module: Kernel

Package: `app/kernel/` — bootstrap, registry, contract verification, dependency graph.
Decisions: [ADR-0002](../adr/0002-modular-monolith-minimal-kernel.md),
[ADR-0004](../adr/0004-entry-points-typed-registry-pydantic.md),
[ADR-0016](../adr/0016-in-process-events-no-broker.md),
[ADR-0021](../adr/0021-plugin-manifest-and-versioning.md).

## Principle

**Modular monolith with a minimal kernel.** The kernel contains only:

- bootstrap and process configuration,
- registration and verification of contracts,
- dependency resolver,
- event bus / dispatch,
- module lifecycle.

All functional areas — **including authentication and persistence** — are modules implementing
registered interfaces ([contracts.md](contracts.md)). Modules are Django apps of two kinds, providers
and plugins ([ADR-0037](../adr/0037-providers-and-plugins.md)).

Modular means *services and their boundaries*, not every object or function. **Not required:**
dynamic installation of untrusted Python code from the UI, process isolation of plugins,
microservices.

## Module installation and activation

- Modules are installed at deployment time by the server operator; module versions are locked in the
  deployment manifest ([../../deployment.md](../../deployment.md)).
- In the admin UI only **enablement/configuration** of plugins can be changed, and — if the plugin
  declares it — per-quiz configuration (`activation_scope`).
- Changing a provider requires a controlled restart and, if needed, a migration. How many of each kind
  may be active: [contracts.md](contracts.md#module-kinds).
- A disabled plugin stays loaded and keeps its data: its routes return 404, the registry hides its ports
  and kernel events skip it. Modules **MUST NOT** connect Django signals ([ADR-0036](../adr/0036-django-web-framework-and-orm.md)).
- A module's package **MUST NOT** be removed on its own: its tables would stay and their foreign keys can
  block deletes of core records. A management command refuses removal while an active quiz or a stored
  revision needs the module, otherwise it reverses the module's migrations; only then is the package
  removed. Details in Stage D.
- Disabling a plugin that an active quiz depends on **MUST** be rejected.
- Compatibility is evaluated **at startup and at publication**. An incompatible plugin blocks
  publication/activation with an explanation.
- Admin may disable a feature for further quizzes without breaking running attempts.
- Old revisions keep the type identifier, version and data needed for re-evaluation/audit.
- A plugin cannot be replaced without a migration strategy for existing revisions.

## Module requirements on settings

- `FR-46` A module may declare in its manifest which quiz or run settings it requires to be enabled,
  set to allowed values or disabled, including settings of other modules (for example the public
  scoreboard). When the module is selected, the admin UI shows these requirements and offers to apply
  them. Conflicts block publication or opening the run, with an explanation.

See [ADR-0034](../adr/0034-module-requirements-on-settings.md).

## Startup sequence

```
 while settings load (no Django imports here):
   load process config (env/secrets)
   └─▶ discover modules (Python entry points)
        └─▶ read & validate manifests (Pydantic)
             └─▶ check api_compatibility against kernel contract version
                  └─▶ resolve dependency graph (requires / optional), detect cycles & missing
                       └─▶ select active providers
                            └─▶ build INSTALLED_APPS, DATABASES, AUTHENTICATION_BACKENDS
 Django setup:
   register typed ports in registry (AppConfig.ready)
   └─▶ mount routes from manifests
 before serving (application entry point):
   verify revisions of active runs still resolvable (type id+version) ─▶ ready
```

Any failure before "ready" aborts startup with an explicit message (no partial boot). Database
migrations run as a release step before the application starts ([../../deployment.md](../../deployment.md)).
Django's system checks do not query the database, so the last verification is done by the kernel, in the
application entry point and in `manage.py modules verify`.

Enabled state comes from `plugin_installation` at request time, so enabling a plugin needs no restart.
`plugin_configuration` follows the same rule; it is added with the first configurable module.

## Registry

- Services call typed ports by an explicit registry key, e.g. `question_type.get('choice.single')`.
- Modules are discovered through standard Python entry points (`importlib.metadata`). Business logic
  cannot be overridden by hooks.

## Events

Internal events: `quiz.published`, `run.opened`, `attempt.submitted`, `run.closed`,
`draw.completed`, `retention.executed`.

- v1.0 dispatch is synchronous and in-process; no queue or broker ([ADR-0016](../adr/0016-in-process-events-no-broker.md)).
- Result submission and score write **MUST** be atomic and idempotent (independent of event
  delivery).

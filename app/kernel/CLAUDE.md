# Module: app/kernel

Application startup and module management. The kernel does not know what a quiz is; that is why it is small and has to stay small.

## Responsibilities

- `discovery.py`, `manifest.py`, `bootstrap.py`: finds modules through entry points, verifies manifests and dependencies, fills `INSTALLED_APPS`.
- `registry.py`: ports of the active modules. `lifecycle.py`: enabling, disabling, verification at startup.
- `events.py`: in-process events. `audit.py`, `models.py`: `AuditEvent`, `AdminUser` (with an optional `email`, which may appear in the quiz footer as a contact, ADR-0054), module installations.
- `middleware.py`: the gate for disabled modules, rejection of multipart and a cap on the request body by `Content-Length` (`BodyLimitMiddleware`, in `MIDDLEWARE` right after the security-headers middleware so that the rejections carry the headers too: 16 MiB, 101 MiB for import and public submission, 413; without a length 411; the same values in MiB are held by `deploy/Caddyfile`, a test guards it, ADR-0066).

Watch out: `blockers` returns texts in the active language, `set_enabled` counts them in English. A plugin with `always_on` cannot be disabled, only enabled.

## Forbidden

- Importing from `app/domain`, `app/api`, `app/plugins`, `app/providers`. The domain registers itself through `register_usage_check` and `register_startup_check`.
- Adding a quiz feature here: a new feature belongs in a module behind a contract.
- Django signals instead of `events`: a disabled module would still receive them.
- `events._dispatch` must not let a handler error out: the operation is already saved. Only the error type goes to the log.

## Public API

`registry.get`, `keys`, `is_enabled`, `owned_by`; `events.emit`, `subscribe`; `audit.record`; `lifecycle.set_enabled`, `blockers`, `verify_startup`; `StartupError`.

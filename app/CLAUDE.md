# Module: app

The application. Own code lives only in subdirectories; the Django configuration stays here: `settings.py`, `urls.py`, `wsgi.py`.

## Responsibilities

- `settings.py`: settings from environment variables, the middleware list, CSP, logging.
- `urls.py`: assembles the public routes, `/admin/` and the module routes from `KVZ_MODULES`.
- `wsgi.py`: runs `verify_startup()` after Django starts.

## Not here

- Quiz logic, models, views: they belong in `domain/` and `api/`.
- Secret values, not even as defaults: `settings.py` does not start without `KVZ_SECRET_KEY`.

## Dependency direction

```
contracts  ←  kernel  ←  domain  ←  api
    ↑           ↑
    └── plugins, providers
```

Enforced by `tests/test_layers.py`.

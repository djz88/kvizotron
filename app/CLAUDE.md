# Modul: app

Aplikace. Vlastní kód je jen v podadresářích, tady zůstává Django konfigurace: `settings.py`, `urls.py`, `wsgi.py`.

## Odpovědnosti

- `settings.py`: nastavení z proměnných prostředí, seznam middlewaru, CSP, logování.
- `urls.py`: skládá veřejné routy, `/admin/` a routy modulů z `KVZ_MODULES`.
- `wsgi.py`: po startu Djanga spustí `verify_startup()`.

## Není tady

- Logika kvízu, modely, view: patří do `domain/` a `api/`.
- Tajné hodnoty, ani jako výchozí: `settings.py` bez `KVZ_SECRET_KEY` nenastartuje.

## Směr závislostí

```
contracts  ←  kernel  ←  domain  ←  api
    ↑           ↑
    └── plugins, providers
```

Hlídá `tests/test_layers.py`.

# Modul: app/kernel

Start aplikace a správa modulů. Kernel neví, co je kvíz; proto je malý a má takový zůstat.

## Odpovědnosti

- `discovery.py`, `manifest.py`, `bootstrap.py`: najde moduly přes entry pointy, ověří manifesty a závislosti, naplní `INSTALLED_APPS`.
- `registry.py`: porty aktivních modulů. `lifecycle.py`: zapnutí, vypnutí, ověření při startu.
- `events.py`: události v procesu. `audit.py`, `models.py`: `AuditEvent`, `AdminUser`, instalace modulů.
- `middleware.py`: brána vypnutých modulů, odmítnutí multipart.

## Zakázáno

- Importovat z `app/domain`, `app/api`, `app/plugins`, `app/providers`. Doména se přihlásí sama přes `register_usage_check` a `register_startup_check`.
- Přidat sem funkci kvízu: nová funkce patří do modulu za kontraktem.
- Django signály místo `events`: vypnutý modul by je dostal dál.
- `events._dispatch` nesmí pustit chybu handleru ven: operace už je uložená. Do logu jde jen typ chyby.

## Veřejné API

`registry.get`, `keys`, `is_enabled`, `owned_by`; `events.emit`, `subscribe`; `audit.record`; `lifecycle.set_enabled`, `verify_startup`; `StartupError`.

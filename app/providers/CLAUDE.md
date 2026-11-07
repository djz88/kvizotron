# Modul: app/providers

Infrastruktura vybraná provozovatelem, mění se jen restartem: `auth_local/` (přihlášení, CLI pro správce), `persistence_sqlite/` (nastavení databáze), `media_local/` (obrázky na svazku), `csv_io/` (čtení a zápis CSV a ZIP). Funkce jsou v `app/plugins/`.

## Odpovědnosti

- `auth_local`: Django backend, `init_admin`, `reset_admin_password`, `passwords.read_password`. Příkazy `createsuperuser` a `changepassword` záměrně jen odmítnou práci.
- `persistence_sqlite`: `database_settings()` s WAL a `transaction_mode: IMMEDIATE`, `healthcheck()`.
- `media_local`: kontrola a zmenšení obrázků, tabulka `media_asset`. Rozhoduje obsah souboru, ne jeho jméno. `remote.py` stahuje z adres a odmítá vnitřní síť (ADR-0043), `media_address_check` drží výsledky hodinové kontroly.
- `csv_io`: soubor importu leží mezi kroky v `imports/` na svazku médií, ZIP se nikdy nerozbaluje na disk, buňky se při zápisu chrání proti vzorcům a při čtení vrací zpět. Co řádek znamená, řeší doména a typy otázek.
- Každý provider uvádí v manifestu pole `settings`, i prázdné (ADR-0042).

## Zakázáno

- Importovat z `app/domain`, `app/api`, `app/plugins`.
- Vypnout providera za běhu: `lifecycle` to odmítne.
- Heslo jako argument příkazu: je vidět v `ps` a historii. Jen `--password-stdin` nebo dotaz na terminálu.
- `set_password` bez `read_password` nebo `validate_password`. `AdminUserManager.create_admin` nevaliduje, to dělá volající.

## Veřejné API

Jen přes manifest a protokoly `AuthenticationProvider`, `PersistenceProvider`, `MediaStorageProvider`, `ImporterProvider`, `ExporterProvider`. Testy: `tests/contracts/`, `tests/providers/`.

Média: fotka účastníka je soukromá (`private`), jen PNG, JPEG a WebP, přestavěná z pixelů. `/media/<id>` na ni odpovídá 404 a podává ji jen routa, která ověří právo (ADR-0047).

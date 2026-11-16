# Modul: app/providers

Infrastruktura vybraná provozovatelem, mění se jen restartem: `auth_local/` (přihlášení, CLI pro správce), `persistence_sqlite/` (nastavení databáze), `media_local/` (obrázky na svazku), `csv_io/` (čtení a zápis CSV a ZIP), `retention/` (záznamy o mazání). Funkce jsou v `app/plugins/`.

## Odpovědnosti

- `auth_local`: Django backend, `init_admin`, `reset_admin_password`, `passwords.read_password`. Příkazy `createsuperuser` a `changepassword` záměrně jen odmítnou práci.
- `persistence_sqlite`: `database_settings()` s WAL a `transaction_mode: IMMEDIATE`, `healthcheck()`.
- `media_local`: kontrola a zmenšení obrázků, tabulka `media_asset`. Rozhoduje obsah souboru, ne jeho jméno. `private_assets_older_than` dává soukromé fotky pro úklid hodinového průchodu. `remote.py` stahuje z adres a odmítá vnitřní síť (ADR-0043), `media_address_check` drží výsledky hodinové kontroly.
- `csv_io`: soubor importu leží mezi kroky v `imports/` na svazku médií, export výsledků v `exports/<id úlohy>/` (tabulka `export_job`, odkaz platí 24 hodin, `path()` ověří správce; úlohu jiného procesu pozná podle `BOOT` a označí `interrupted`, `claim_next()` hlídá 1 běžící úlohu na správce a 2 v aplikaci, ADR-0055), ZIP se nikdy nerozbaluje na disk, buňky se při zápisu chrání proti vzorcům a při čtení vrací zpět. Co řádek znamená, řeší doména a typy otázek. `delete_for_runs` po smazání dat běhu odstraní úlohy a soubory, které ho jmenují nebo berou všechny běhy kvízu.
- `retention`: tabulka `retention_job` se záznamy o smazání: počty, nikdy osobní hodnota; otisk e-mailu ven nevrací. Co smazat a kdy, řeší doména.
- Každý provider uvádí v manifestu pole `settings`, i prázdné (ADR-0042).

## Zakázáno

- Importovat z `app/domain`, `app/api`, `app/plugins`.
- Vypnout providera za běhu: `lifecycle` to odmítne.
- Heslo jako argument příkazu: je vidět v `ps` a historii. Jen `--password-stdin` nebo dotaz na terminálu.
- `set_password` bez `read_password` nebo `validate_password`. `AdminUserManager.create_admin` nevaliduje, to dělá volající.

## Veřejné API

Jen přes manifest a protokoly `AuthenticationProvider`, `PersistenceProvider`, `MediaStorageProvider`, `ImporterProvider`, `ExporterProvider`, `ResultsExporterProvider`, `RetentionProvider`. Testy: `tests/contracts/`, `tests/providers/`.

Média: fotka účastníka je soukromá (`private`), jen PNG, JPEG a WebP, přestavěná z pixelů. `/media/<id>` na ni odpovídá 404 a podává ji jen routa, která ověří právo (ADR-0047).

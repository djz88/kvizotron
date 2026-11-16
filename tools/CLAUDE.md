# Modul: tools

Pomocné skripty pro vývoj, volané z `Makefile`. Do image nejdou a aplikace je neimportuje.

## Odpovědnosti

- `messages.py`: `make messages`. Vytáhne texty a zkompiluje katalogy z `ROOTS`.
- `tech_debt.py`: `make tech-debt-*`. Pracuje s `docs/_architecture/TECH_DEBT.md` a archivem.
- `plan_check.py`: `make plan-check`. Porovná soubory z plánu s gitem.
- `load_deadline.py`: zátěžový test odeslání v jednu chvíli (AC-07).
- `load_participants.py`: `make load` (spolu s `deploy/load.sh`). 50 účastníků začne, zavolá `check` tam, kde ho stránka chce, a pak naráz odešle formulář s fotkou (`--photo-file`: skutečný obrázek, `make load` ho vyrobí Pillow v kontejneru, asi 700 kB; bez něj JPEG sestavený bez Pillow z malého obrázku a výplně, který zkouší jen nahrání, ne dekódování); jeden řádek `PASS`/`FAIL`/`INFO` na kritérium (2xx, stejný výsledek při opakovaném odeslání, nejpomalejší pod 5 s) a řádek `WINDOW first=… last=…` s okénkem odesílání. S `--probe-from ADRESA` zkouší, zda aplikace počítá limit startů zvlášť pro různé zdroje (adresa z LAN proti smyčce 127.0.0.x; 127.0.0.1 a 127.0.0.2 od sebe nerozliší). Co zná jen databáze nebo log (každý pokus a fotka jednou, zámek, překryv záloh s okénkem, obnova ze zálohy po změně živých dat, počet dotazů stránky), kontroluje `deploy/load.sh` přes `docker compose exec`; ten běží jen v projektu `kvizotron-load` na portech `LOAD_HTTP_PORT` a `LOAD_HTTPS_PORT`.

## Zakázáno

- Závislost `load_participants.py`, `tech_debt.py` a `plan_check.py` na čemkoli mimo standardní knihovnu: běží přes `python3` bez `uv`.
- Přepisovat `.po` ručně mimo `msgstr`: `make messages` je přegeneruje.

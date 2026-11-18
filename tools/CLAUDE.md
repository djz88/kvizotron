# Modul: tools

Pomocné skripty pro vývoj, volané z `Makefile`. Do image nejdou a aplikace je neimportuje.

## Odpovědnosti

- `messages.py`: `make messages`. Vytáhne texty a zkompiluje katalogy z `ROOTS`.
- `tech_debt.py`: `make tech-debt-*`. Pracuje s `docs/_architecture/TECH_DEBT.md` a archivem.
- `plan_check.py`: `make plan-check`. Porovná soubory z plánu s gitem.
- `private_traces.py`: hooky `private-traces*` z `.pre-commit-config.yaml` (commit, zpráva commitu, push). Odmítne domovský adresář, dočasný adresář agenta, odkaz na sezení agenta a slova ze seznamu `.git/info/private-traces`, který je mimo git (jméno, adresa domácí sítě, e-mail; jedno na řádek, `#` je komentář). Seznam hledá přes `git rev-parse --git-common-dir`, takže worktree sdílí seznam hlavní kopie. Bez seznamu hooky projdou s připomenutím; `list` (z `make hooks` a `make doctor`) hlásí, zda existuje, a `make private-traces` ho založí prázdný. Řádek `allow TEXT [CESTA…]` v témže seznamu je výjimka, ne slovo: nález uvnitř TEXT projde jen v jmenovaných souborech (cesta od kořene repozitáře), bez cesty všude; zpráva commitu bere jen výjimky pro všude, push je posuzuje po souborech. Slouží pro vlastníka v `.github/CODEOWNERS` a `SECURITY.md`; holé slovo jinde dál neprojde.
- `load_deadline.py`: zátěžový test odeslání v jednu chvíli (AC-07).
- `load_participants.py`: `make load` (spolu s `deploy/load.sh`). 50 účastníků začne, zavolá `check` tam, kde ho stránka chce, a pak naráz odešle formulář s fotkou (`--photo-file`: skutečný obrázek, `make load` ho vyrobí Pillow v kontejneru, asi 700 kB; bez něj JPEG sestavený bez Pillow z malého obrázku a výplně, který zkouší jen nahrání, ne dekódování); jeden řádek `PASS`/`FAIL`/`INFO` na kritérium (2xx, stejný výsledek při opakovaném odeslání, nejpomalejší pod 5 s) a řádek `WINDOW first=… last=…` s okénkem odesílání. S `--probe-from ADRESA` zkouší, zda aplikace počítá limit startů zvlášť pro různé zdroje (adresa z LAN proti smyčce 127.0.0.x; 127.0.0.1 a 127.0.0.2 od sebe nerozliší). Co zná jen databáze nebo log (každý pokus a fotka jednou, zámek, překryv záloh s okénkem, obnova ze zálohy po změně živých dat, počet dotazů stránky), kontroluje `deploy/load.sh` přes `docker compose exec`; ten běží jen v projektu `kvizotron-load` na portech `LOAD_HTTP_PORT` a `LOAD_HTTPS_PORT`.

## Zakázáno

- Závislost `load_participants.py`, `tech_debt.py`, `plan_check.py` a `private_traces.py` na čemkoli mimo standardní knihovnu: běží přes `python3` bez `uv`.
- Přepisovat `.po` ručně mimo `msgstr`: `make messages` je přegeneruje.

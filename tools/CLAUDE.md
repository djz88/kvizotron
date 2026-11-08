# Modul: tools

Pomocné skripty pro vývoj, volané z `Makefile`. Do image nejdou a aplikace je neimportuje.

## Odpovědnosti

- `messages.py`: `make messages`. Vytáhne texty a zkompiluje katalogy z `ROOTS`.
- `tech_debt.py`: `make tech-debt-*`. Pracuje s `docs/_architecture/TECH_DEBT.md` a archivem.
- `plan_check.py`: `make plan-check`. Porovná soubory z plánu s gitem.
- `load_deadline.py`: zátěžový test odeslání v jednu chvíli (AC-07).

## Zakázáno

- Závislost `tech_debt.py` a `plan_check.py` na čemkoli mimo standardní knihovnu: běží přes `python3` bez `uv`.
- Přepisovat `.po` ručně mimo `msgstr`: `make messages` je přegeneruje.

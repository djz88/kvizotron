# Modul: tools

Pomocné skripty pro vývoj, volané z `Makefile`. Do image nejdou a aplikace je neimportuje.

## Odpovědnosti

- `messages.py`: `make messages`. Vytáhne texty a zkompiluje katalogy z `ROOTS`.
- `tech_debt.py`: `make tech-debt-*`. Pracuje s `docs/_architecture/TECH_DEBT.md` a archivem.

## Zakázáno

- Závislost `tech_debt.py` na čemkoli mimo standardní knihovnu: běží přes `python3` bez `uv`.
- Přepisovat `.po` ručně mimo `msgstr`: `make messages` je přegeneruje.

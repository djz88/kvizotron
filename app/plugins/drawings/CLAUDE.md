# Modul: app/plugins/drawings

Plugin `drawings.manual`, port `drawing`: čistá pravidla losování (FR-37, ADR-0013). Deterministické pořadí snímku (`order`: seřazená a jedinečná id), otisk snímku (`fingerprint`: sha256 z id spojených `\n`) a výběr přes `secrets.SystemRandom().sample` (`select`). Jméno algoritmu je v `algorithm` a ukládá se u losování.

## Co modul obsahuje

`selection.py` (`ManualDrawing`), `manifest.py` bez nastavení, `apps.py`.

## Co modul není

Nesahá do databáze ani do požadavku. Kdo je oprávněný, záznamy losování, náhradníci a audit jsou v doméně; plugin dostane id účastníků (ne jména) a vrátí pořadí nebo výběr.

## Zakázáno

Importovat z `app/domain`, `app/api` nebo z jiného pluginu: smí jen `app.contracts`. Náhoda jen ze `secrets`, nikdy `random` s vlastním semínkem.

# Modul: app/plugins/results

Plugin `results.local`, port `result_view`: čistá pravidla výsledků. Který pokus účastníka se počítá (`pick_official`), pořadí a shody žebříčku (`rank`, ADR-0026) a souhrn skóre pro statistiky (`summarize`).

## Co modul obsahuje

`ranking.py` (`LocalResultView`), `manifest.py` s dvanácti nastaveními žebříčku (rozsah global a kvíz, platí pro celý běh), `apps.py`.

## Co modul není

Nesahá do databáze ani do požadavku. Pokusy, viditelnost, jména a mezipaměť řeší `app/domain/results.py` a `app/domain/run_stats.py`; plugin dostane `ScoreEntry` a vrátí pořadí.

## Zakázáno

Importovat z `app/domain`, `app/api` nebo z jiného pluginu: smí jen `app.contracts`. Náhoda u shod jen z hodnoty uložené u běhu (`seed`), nikdy `random`.

# Modul: app/plugins/rewards

Plugin `rewards.threshold`, port `reward`: čistá pravidla odměn za práh. Podíl prahu z pokusu (`share`), zda pokus práh dosáhl (`reached`, `>=` na přesných `Decimal`) a které prahy účastník dostane podle nastavení `reward_thresholds` (`qualifies`: `highest` jen největší podíl, shoda podle pořadí pravidel; `all` všechny dosažené).

## Co modul obsahuje

`thresholds.py` (`ThresholdReward`), `manifest.py` se třemi nastaveními odměn (`reward_source`, `reward_thresholds`, `winner_contact`; rozsah global a kvíz, platí pro celý běh), `apps.py`.

## Co modul není

Nesahá do databáze ani do požadavku. Pravidla, nároky, kopie na běh a transakce řeší doména; plugin dostane `ThresholdRule` a `AttemptFigures` a vrátí id pravidel. Losování je v `app/plugins/drawings/`.

## Zakázáno

Importovat z `app/domain`, `app/api` nebo z jiného pluginu: smí jen `app.contracts`. Porovnávat zaokrouhlená čísla nebo `float`.

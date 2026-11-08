---
name: kvizotron-add-setting
description: Use when adding, moving or changing the scope of a setting in Kvízotron, including a request phrased as a switch, an option, or "let the admin choose", and when a module needs a value an admin can set.
---

# Přidání nastavení

Pravidla jsou v ADR-0042. Tady je pořadí a místa, která test sám nepřipomene.

## 1. Než začneš psát kód

Je to vůbec nastavení? Hodnota, která se dědí, ano. Obsah otázky (body, zdroje, strategie) ne.

Zeptej se uživatele přes `AskUserQuestion`, pokud to zadání výslovně neříká:

- **Rozsah.** Výchozí je global → kvíz → otázka. Užší nabídni jen s konkrétním důvodem, který pak půjde do `scope_reason`.
- **Výchozí hodnota**, pokud mění chování stávajících kvízů.

Skupinu a úroveň (`group`, `level`) zvol sám a napiš je do zprávy: skupina podle toho, čeho se nastavení týká (`playing`, `answers`, `participants`, `scoreboard`, `data`, `look`, `technical`), úroveň `basic` jen pro to, co admin mění u většiny kvízů. Bez nich je nastavení `technical` a `advanced` (ADR-0052).

Spěch ani „pak na to mrknu“ tuhle otázku neruší. Rozsah se v uložených datech a importech mění špatně. Nemůžeš-li se zeptat, zastav se a napiš otázku; rozsah nevybírej za uživatele.

## 2. Kam to patří

| Vlastník | Kde |
|---|---|
| Doména | konstanta, případně `StrEnum`, a položka `CATALOGUE` v `app/domain/settings.py` s `group=` a případně `level=BASIC` |
| Modul | pole `settings` v jeho `manifest.py`, vzor je v `app/plugins/questions/image_answer/manifest.py` |

Rozsah otázky ještě potřebuje jedno z toho:

- typ otázky klíč vrací v `question_settings()`,
- platí pro všechny typy: `ALL_TYPES_QUESTION_SETTINGS`.

## 3. Čtení hodnoty

- Vždy `settings.resolve(key, quiz, question)`. `AppSetting` se přímo nečte.
- Plugin nastavení nečte: dostane je v `quiz_settings` od API.
- Rozhodni, kdy se hodnota čte, a napiš to: při každém načtení stránky, při losování (`none_option`), nebo se kopíruje na běh (`attempt_limit`).

## 4. Co projít podle toho, na co nastavení působí

| Otázka | Kde |
|---|---|
| Účastník to vidí? | `app/api/play.py`, a stejně i náhled: `app/domain/preview.py`, `app/api/admin_preview.py` |
| Testovací odkaz se má chovat stejně? | `app/domain/run_links.py` |
| Hodnota jiného druhu než výběr? | formuláře v `app/api/admin_forms.py` mají výjimky, vzor je `ATTEMPT_LIMIT` |
| Vylučuje se s jiným nastavením? | `is_flow_conflict`, `is_visibility_conflict` v `settings.py`; modul přes `settings_requirements` |
| Je na otázce? | Patří k revizi, změna dělá koncept. Projdi `app/domain/revision_diff.py`, `app/domain/question_import.py`, `app/domain/question_export.py` |

## 5. Hotovo je, když

- Testy ukazují dědění na každém nabízeném rozsahu, smazání přepsání a skutečný účinek na stránce, nejen uloženou hodnotu.
- `make messages` proběhl a `msgstr` v cs i uk jsou vyplněné.
- `docs/_architecture/modules/api-ui.md` uvádí nastavení v tabulce „Where things are set“. Modul navíc ve svém souboru v `docs/_architecture/plugins/` nebo `providers/`. Nové chování má řádek `AC-xx`.
- `make quality` prošel. `tests/contracts/test_settings_rule.py` hlídá rozsahy i pole formulářů, `tests/test_wiring.py` že hodnotu někdo čte. Jestli má účinek, ověř přes `kvizotron-check-applied`.

## Časté chyby

| Chyba | Správně |
|---|---|
| Užší rozsah, protože je to rychlejší | Rychlost není důvod pro `scope_reason`. Zeptej se. |
| Volba bez štítku v `value_labels` | Validace ji odmítne. Každá volba má přeložený štítek. |
| Účinek jen v `play.py` | Náhled ukáže jiné chování než běh. |
| Test jen na `resolve` | Test musí vidět i stránku, kterou nastavení mění. |

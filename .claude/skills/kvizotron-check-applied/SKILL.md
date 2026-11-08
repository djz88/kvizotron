---
name: kvizotron-check-applied
description: Use when Kvízotron work looks finished and before saying so, before review-roles, before a merge, or when asked whether everything from a plan or spec was really applied and connected.
---

# Kontrola, že je všechno použité a napojené

Odpovídá na jednu otázku: **je to, co mělo vzniknout, opravdu v kódu a dá se k tomu dojít?** Dělá se spuštěním, ne čtením.

| Tady | V `review-roles` |
|---|---|
| Fakta z příkazů: soubor se změnil, adresa vede na stránku, funkci někdo volá | Úsudek ze čtení: je to dobře navržené, bezpečné, srozumitelné |

Kvalitu kódu tady nehodnoť. Výsledek předej do `review-roles` jako vstup, ať ho role nedělají znovu.

## 1. Plán proti gitu

```bash
make plan-check plan=docs/superpowers/plans/<plán>.md base=main
```

- „Plan names it, it did not change“: u každého souboru napiš proč, nebo změnu doplň. Tiše to nepřecházej.
- „Changed, not committed“: co není v commitu, není hotové.
- „The plan does not name it“: jedna věta ke každému. Není to chyba, ale neplánovaná změna musí mít důvod.

Práce bez plánu tenhle krok přeskakuje, a zpráva to řekne.

Kontrola vidí jen soubory, které plán jmenuje. Ztracenou změnu v souboru mimo plán nenajde, a že je změna v souboru správná, neověří.

## 2. Napojení

```bash
make wiring
```

Hlídá moduly, šablony, adresy, skripty, styly, nastavení, události a přihlášení do administrace. Seznam výjimek v `tests/test_wiring.py` se jen zmenšuje. Novou položku tam nepřidávej, aby test prošel; oprav napojení.

## 3. Spec proti skutečnosti

Vypiš tabulku se řádkem za každý cíl a každou odrážku chování ze specu:

| Požadavek | Vstup (adresa, příkaz) | Jak ověřeno | Důkaz |
|---|---|---|---|

Důkaz je jedno z toho:

- název testu, který jde přes skutečnou adresu a spadl by bez té změny,
- řádek z `make smoke`,
- screenshot z `kvizotron-browser-walkthrough`.

Test funkce není důkaz napojení: funkce může fungovat a nikdo ji nevolá. Dotýká-li se změna víc vrstev, **REQUIRED SUB-SKILL:** `kvizotron-check-integration`; jeho tabulka je důkazem pro dotčené řádky.

Řádek bez důkazu napiš jako **neověřeno**. Hotovo to není, dokud ho nedoplníš nebo uživatel nerozhodne jinak.

## 4. Běh mimo testy

| Změna | Ověř |
|---|---|
| Migrace, závislost, Docker, nový modul, nový soubor v `app/api/assets/` | `make smoke` na čistém sestavení |
| Vzhled, skript, HTMX, překlad | `kvizotron-browser-walkthrough` |
| Termíny, souběh | `tools/load_deadline.py` nebo test s řízeným časem |

Když běží `kvizotron-browser`, spusť smoke s `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543`.

## 5. Výstup

Výsledky kroků 1 až 4 s výstupem příkazů a tabulkou z kroku 3. Na konci seznam **neověřeno**, i když je prázdný.

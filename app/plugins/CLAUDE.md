# Modul: app/plugins

Funkce, které se dají zapínat a vypínat: `questions/` (typy otázek), `scoring/` (bodování), `quiz_flow/` (režimy navigace), `theme_default/` (téma), `participants/` (pravidla účastníků, ADR-0049), `results/` (oficiální pokus, pořadí žebříčku a souhrny, ADR-0051), `rewards/` (dosažené prahy odměn a tři nastavení odměn, ADR-0053), `drawings/` (pořadí, otisk a výběr losování, ADR-0013 a ADR-0053). Infrastruktura je v `app/providers/`.

## Co modul obsahuje

`manifest.py` s povinným polem `settings` (ADR-0042), zápis do `[project.entry-points."kvizotron.modules"]`, `apps.py`, vlastní šablony v `jinja2/<název>/` a katalog v `locale/`. Nový katalog patří do `ROOTS` v `tools/messages.py`.

## Zakázáno

- Importovat z `app/domain`, `app/api`, `app/providers` nebo z jiného pluginu: smí jen `app.contracts`.
- Klíč odpovědi v `public_payload()` nebo v `render_public`.
- Skládat HTML ručně: výstup se značí jako bezpečný, proto kreslí jen šablona s autoescape.
- Vlastní tabulky bez migrace v modulu; úprava tabulek domény.

## Pozor

- Každý typ otázky má `tests/contracts/test_<typ>.py`, který dědí `QuestionTypeContract`, a tím i testy escapování a `describe_definition`.
- `describe_definition` musí změnit výstup při změně kteréhokoli pole definice, jinak ji přehled změn neukáže.
- Vstupy se jmenují `<id otázky>:<pole>`. Hodnoty přicházejí jako řetězce; pole končící `[]` přijde jako seznam pod jménem bez závorek.
- Typ známku počítá v `grade`, strategie ji jen váží. Nastavení plugin nečte: co potřebuje, dostane v `quiz_settings`.
- Obrázky jsou v definici jako `asset`, případně `source`; co se ukáže, rozhodne API a doplní to do klíče `url`.
- Sdílený obrázek otázky je v `app/contracts/question_image.py` a makro v `admin/_image_fields.html`, protože pluginy nesmí importovat jeden druhý.
- Typ se soubory vrací `file_fields`; hodnotu takového pole dosazuje jen API ze skutečně přijatého souboru. `summarize` vrací prostý text pro veřejný průchod a soukromý odkaz, nikdy značky.
- `from_csv` skládá formulář editoru a volá `parse_admin`, takže soubor odmítne totéž co editor. Buňku s obrázkem jen předá ve `source`, adresu od souboru rozlišuje doména.
- Některé validační hlášky pluginů jsou zatím anglicky.

## Veřejné API

Žádné importy zvenčí; ostatní znají modul jen přes registr a protokol.

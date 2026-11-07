# Modul: app/api

Tenká view a stránky: převede požadavek na volání služby v `app/domain/` a výsledek na HTML. Pravidla tady nejsou.

## Odpovědnosti

- Veřejné stránky: `public.py`. Hraní: `play.py` (start, submit, switch, revision-status).
- Testovací odkazy: `public.test_link`, `admin_links.py`. Náhled: `admin_preview.py` na šablonách `public/`. Import a export: `admin_import.py`, `admin_export.py`.
- Administrace: `admin_*.py`, routy v `admin_urls.py`, formuláře v `admin_forms.py`.
- `rendering.py` kreslí stránky a otázky, `i18n.py` volí jazyk, `jinja.py` je prostředí šablon.
- Šablony: `jinja2/admin/`, `jinja2/public/`. Vlastní katalog v `locale/`. Veřejné stránky dědí `public/base.html`, stránky kvízu v administraci vkládají `admin/_quiz_header.html`.

- `admin_workspace.py` sestaví hlavičku kvízu, pravidlo hlavního tlačítka je v `app/domain/quiz_state.py`.

## Zakázáno

- Importovat z `app/plugins` a `app/providers`: pluginy se berou z registru přes `registry.get`.
- Rozhodovat o skóre, revizích nebo stavu kola: to dělá doména.
- Admin formulář bez `{{ csrf_input }}` a nová `csrf_exempt` routa mimo `start`, `submit`, `switch`: hlídá `tests/api/test_request_limits.py`.
- Inline skript nebo styl: CSP je nepustí.
- Poslat účastníkovi cokoli jiného než `public_payload()`.

## Pozor

- HTMX atributy se dědí: prvek uvnitř `<form hx-target>` potřebuje vlastní `hx-target` a `hx-disabled-elt`.
- Texty v `admin*` souborech a šablonách jsou cs a en, ostatní i uk (`tests/test_translations.py`).
- Téma může přepsat kteroukoli šablonu, protože se načítá před `app.api`.

- Veřejná stránka kvízu předává `palette_quiz`, jinak `page()` použije globální barvy. Administrace ho nepředává nikdy.
- Menu jsou `<details open>`. `assets/nav.js` je na úzké obrazovce zavře, bez JavaScriptu zůstanou otevřená.
- Soubory z editoru otázek ukládá `_form_with_uploads` dřív, než formulář dostane plugin. Multipart jinde než tam a na `/admin/import/new` nejde (`RefuseMultipartMiddleware`).
- `assets/sortable.js` a `assets/editor.js` jen vylepšují: bez JavaScriptu je pořadí seznam s výběrem pozic a odeslání dál funguje.
- `#play` obsahuje i nadpis stránky kvízu, aby ho spuštění nahradilo. Karta je až v `_questions.html` a `_result.html`.

## Veřejné API

Pro ostatní moduly žádné. `not_archived` a `edit_page` z `admin_quizzes.py` používá jen `admin_revisions.py`.

Hodnocení, fotky a výsledky: `admin_grading.py` je záložka Hodnocení. `/v/<token>` a `/q/<slug>/r/<run>/answers` odpovídají 200 s jednou zprávou a odmítnutá fotka 204, aby se token ani existence fotky nedostaly do logu. Co smí kdo vidět, rozhoduje `app/domain/visibility.py`, ne šablona.

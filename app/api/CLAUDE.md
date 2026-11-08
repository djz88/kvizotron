# Modul: app/api

Tenká view a stránky: převede požadavek na volání služby v `app/domain/` a výsledek na HTML. Pravidla tady nejsou.

## Odpovědnosti

- Veřejné stránky: `public.py`. Hraní: `play.py` (start, resume, submit, switch, revision-status, zadání kódu). `assets/resume.js`: kopie rozpracovaného pokusu v `localStorage`, jen vylepšení. `code_limit.py`: limit špatných kódů na IP v paměti procesu.
- Testovací odkazy: `public.test_link`, `admin_links.py`. Náhled: `admin_preview.py` na šablonách `public/`. Import a export: `admin_import.py`, `admin_export.py`.
- Administrace: `admin_*.py`, routy v `admin_urls.py`, formuláře v `admin_forms.py`.
- `rendering.py` kreslí stránky a otázky, `i18n.py` volí jazyk, `jinja.py` je prostředí šablon.
- Šablony: `jinja2/admin/`, `jinja2/public/`. Vlastní katalog v `locale/`. Veřejné stránky dědí `public/base.html`, stránky kvízu v administraci vkládají `admin/_quiz_header.html`.

- `admin_workspace.py` sestaví hlavičku kvízu, pravidlo hlavního tlačítka je v `app/domain/quiz_state.py`.

## Zakázáno

- Importovat z `app/plugins` a `app/providers`: pluginy se berou z registru přes `registry.get`.
- Rozhodovat o skóre, revizích nebo stavu kola: to dělá doména.
- Admin formulář bez `{{ csrf_input }}` a nová `csrf_exempt` routa mimo `start`, `resume`, `submit`, `switch`: hlídá `tests/api/test_request_limits.py`.
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

Profil `none`: po odeslání pokus neexistuje, token bez řádku dává `attempt_gone` (410) bez skóre. Resume bere token jen v těle POST a nepotřebuje cookie s kódem; odmítnutí, po kterém kopie nemá smysl, nese `X-Kvz-Drop-Copy`.

Přepínač a skupiny: `admin_view.py` drží cookie `kvz_admin_view` a `group_fields`, které stránky nastavení a plán běhu kreslí přes `admin/_setting_groups.html`. Skryté pole se neodesílá: ukládání musí prázdnou hodnotu brát jako „beze změny“ (ADR-0052). Testy pokročilých polí používají fixture `showing_all`.

Žebříček: `scoreboard.py` kreslí `/q/<slug>/r/<běh>/scoreboard` a fragment `/rows`, který HTMX obnovuje každých 15 s, dokud není `board.final`. Jazyk se aktivuje dřív, než se sestaví důvody skrytí. Vlastní místo u výsledku dává `scoreboard.place_context`.

Účastníci: cookie `kvz_p_<běh>` a `kvz_c_<běh>` nastavuje jen `play.py`. Na zamčeném běhu se kód kontroluje dřív než jméno nebo účastník. Odpověď, která vrací napsané jméno nebo e-mail, má `private, no-store`; `/v/<token>/identity` odmítá s 200.

Odměny: `admin_rewards.py` je záložka kvízu Odměny (šablona) a stránka odměn běhu s nároky a ručním udělením. Strukturu pravidla mění jen u naplánovaného běhu, jinak ukládá jen texty; `RewardConflict`, `RuleLocked` a `RuleInvalid` převádí na zprávy. Stránka losování běhu (`/admin/runs/<id>/draw`, šablona `admin/prize_draw.html`) GET nic nemění; akce jsou POST a `DrawRefused` převádí na větu (409, chybějící důvod 400). E-mail vítěze je jen na stránce odměn a losování běhu. Plán a otevření běhu v `admin_runs.py` a `admin_quizzes.py` chytají `RewardConflict` stejně. Veřejně: vlastní odměny u výsledku a na `/v/<token>` dává `play.rewards_shown`, názvy odměn na stránce kvízu `public.py` a zveřejněné výherce `scoreboard.py`, i u skrytého žebříčku, jen při načtení stránky, ne ve fragmentu `/rows`.

Hodnocení, fotky a výsledky: `admin_grading.py` je záložka Hodnocení. `/v/<token>` a `/q/<slug>/r/<run>/answers` odpovídají 200 s jednou zprávou a odmítnutá fotka 204, aby se token ani existence fotky nedostaly do logu. Co smí kdo vidět, rozhoduje `app/domain/visibility.py`, ne šablona.

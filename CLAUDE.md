# Kvízotron — pokyny pro agenty

`AGENTS.md` je symlink na tento soubor.

Typ projektu: self-hosted webová aplikace v Pythonu (Django) — **etapa A a milníky B1, B1.5, B2, B3, B4, B5 a B6 hotové: admin UI, kvízy ve třech jazycích, bezpečné změny kvízu za běhu, navigace a vzhled, typy otázek Výběr a Přiřazení, obrázky, bodování a zdroje, banky otázek, režimy průchodu, odhalení odpovědí, obrázky z adresy, náhled, testovací odkazy, import a export otázek, typy Číslo, Text a Fotka, hodnocení fotek, uložené odpovědi, soukromý odkaz na výsledek a veřejný průchod**
Manifesty: `pyproject.toml`, `uv.lock`

## Dokumentace

Zdrojem pravdy pro architekturu je `docs/_architecture/`; začni v `docs/_architecture/README.md`.

- `docs/_architecture/overview.md` — cíle, rozsah v1.0, co je mimo rozsah
- `docs/_architecture/architecture.md` — pohledy na systém, průběh start/submit, stack, struktura kódu
- `docs/_architecture/modules/` — jádro: kernel, kontrakty, doména, API a UI
- `docs/_architecture/providers/` — referenční provideři (infrastruktura), jeden soubor na providera
- `docs/_architecture/plugins/` — referenční pluginy (funkce), jeden soubor na plugin
- `docs/_architecture/data-model.md`, `docs/_architecture/security.md`
- `docs/_architecture/adr/` — rozhodnutí ve formátu MADR 4
- `docs/_architecture/roadmap.md`, `acceptance-criteria.md`, `open-questions.md`
- `docs/_architecture/TECH_DEBT.md`, `TECH_DEBT_archive.md` — vědomě odložené nedodělky
- `docs/plugin-api.md`, `docs/deployment.md`, `docs/privacy.md`

Adresáře v `app/`, `tests/` a `tools/` mají vlastní `CLAUDE.md`: co v nich je, co v nich není a co smějí importovat. Co se týká celého projektu, je jen tady.

## Přehled

Kvízotron je platforma pro vícejazyčné kvízy (cs/en/uk) a soutěže. Veřejnost hraje bez registrace přes URL nebo QR kód. Lokální admini tvoří kvízy, spouštějí soutěžní kola se žebříčkem a odměnami a provádějí auditovatelné losování. Cílová kapacita je asi 50 souběžných účastníků.

Architektura je modulární monolit s minimálním kernelem: všechny funkční oblasti včetně autentizace a persistence jsou moduly za kontrakty. Moduly jsou dvou druhů: provideři (infrastruktura: databáze, auth, import/export) a pluginy (funkce: typy otázek, témata, zobrazení výsledků). Stack: Django, gunicorn, Jinja2, HTMX, Pydantic, SQLite (WAL), Caddy, Docker Compose.

Stav: hotová etapa A (milníky A1–A4), B1, B1.5, B2, B3, B4, B5 a B6: kernel, provideři, admin UI, hraní kvízu v cs/en/uk s typy Výběr a Přiřazení, nahrávání obrázků, bodování část za část, zdroje u výsledku, QR, skóre na serveru, nastavení s přepsáním u kvízu, přepnutí běžícího kola na novou revizi, přehled změn, návrat ke starší revizi, duplikace a archivace kvízu, popis kvízu, hlavní tlačítko podle stavu, pět sad barev, veřejné menu, banky otázek s losováním bez opakování, míchání, tři režimy průchodu s ukazatelem postupu, odhalení odpovědí, přeložené vysvětlení, obrázky z adresy jako kopie nebo z jejich serveru, nastavení s přepsáním u otázky, náhled bez ukládání, testovací odkazy na vybranou verzi, import otázek z CSV a ZIP a jejich export, typy Číslo, Text a Fotka, hodnocení fotek po otázkách nebo po pokusech, volba ukládání a viditelnosti odpovědí, soukromý odkaz na výsledek, veřejný průchod po skončení běhu a požadavky modulů na nastavení. Není určeno na veřejné nasazení, dokud nejsou limity požadavků (D5). Další je etapa C (`docs/_architecture/roadmap.md`).

## Příkazy

Funguje teď:

- `make help` — seznam cílů
- `make hooks` — nainstaluje git hooky
- `make setup` — nainstaluje závislosti; vyžaduje uv 0.13 nebo novější (`uv self update`)
- `make setup-reset` — `make clean` a `make setup`; verze bere z `uv.lock`, nepovyšuje je
- `make doctor` — ověří nástroje (uv, docker, hooky)
- `make clean` — smaže build prostředí (`.venv`, cache nástrojů, výstupy buildu); `.env`, data, zálohy ani worktree se nemažou
- `make lint` — ruff a mypy; `make lint fix` opraví, co jde
- `make test` — pytest
- `make secrets` — gitleaks ve staged změnách a v historii gitu; soubory mimo git nekontroluje
- `make quality` — lint, testy, gitleaks a kontrola `TECH_DEBT.md`; totéž běží v CI
- `make smoke` — spustí nasazení v Dockeru a ověří ho
- `make messages` — vytáhne texty k překladu a zkompiluje katalogy; `.po` i `.mo` jsou v gitu
- `make worktree`, `make worktree-create JMÉNO`, `make worktree-remove JMÉNO` — pracovní kopie v `.worktrees/`; větev se smaže, jen když je mergnutá
- `make tech-debt-check`, `tech-debt-tidy`, `tech-debt-create title="…"`, `tech-debt-resolve id=TD-NNN` — práce s `TECH_DEBT.md` a archivem

Pro tyto kontroly nevymýšlej jiné příkazy.

## Konvence

Název:

- Aplikace se jmenuje **Kvízotron** (texty, UI, dokumentace). Technické názvy zůstávají bez diakritiky: `kvizotron` (adresář, git repozitář, balíčky, identifikátory).

Dokumentace:

- Dokumentace v `docs/` je anglicky, diagramy jen jako text nebo ASCII.
- Každý fakt má jediné místo, ostatní soubory na něj odkazují. Mapa FR → soubor je v `docs/_architecture/README.md`.
- ID `FR-xx`, `AC-xx`, `ADR-NNNN`, `OQ-xx` a `TD-NNN` jsou stabilní, neměň jejich význam ani je znovu nepoužívej.
- `FR-xx` se definuje jen jednou, jako odrážka ``- `FR-xx` `` v souboru podle mapy.
- Závaznost: MUST = požadavek v1.0, SHOULD = doporučení, LATER = mimo v1.0.
- ADR se statusem `proposed` ještě nejsou rozhodnuté. Neber je jako hotovou věc: před implementací dotčené oblasti je nech rozhodnout člověkem a aktualizuj `open-questions.md`.
- Architektonicky významná změna přidá nové ADR, nebo nahradí staré (`superseded by ADR-NNNN`).

Návrh, který musí implementace dodržet:

- Nové funkce patří do modulu (providera nebo pluginu, ADR-0037) za kontraktem, ne do kernelu. Kernel obsahuje jen bootstrap, konfiguraci, registr, ověření kontraktů, řešení závislostí, události a životní cyklus.
- V UI se `QuizRun` česky jmenuje běh, anglicky run. Slovo kolo se v textech nepoužívá.
- Nesměšuj `Quiz`, `QuizRevision`, `QuizRun`, `Attempt`, `Participant` a `Scoreboard` (`docs/_architecture/modules/domain.md`).
- Publikovaná revize je neměnná. Restart soutěže vytvoří nové kolo, nikdy nepřebírá výsledky.
- Skóre počítá vždy server, klientskému skóre, řešení ani časům se nevěří. `public_payload()` nikdy neobsahuje klíč odpovědí.
- Každý modul musí projít sdílenými kontraktovými testy v `tests/contracts/`.
- Nové nastavení se dědí global → kvíz → otázka, užší rozsah musí mít napsaný důvod (ADR-0042). Každý modul uvádí pole `settings` v manifestu, a pokud žádné nemá, tak `[]`; bez toho testy neprojdou. Kam nastavení patří, rozhoduje ten, kdo ho přidává: agent se zeptá uživatele, pokud to zadání neříká.

## Pravidla

- Do kódu, konfigurace, logů ani commitů nepatří tajné údaje (hesla, tokeny, klíče); patří do proměnných prostředí nebo do správce tajných údajů.
- Vstupy zvenčí (uživatel, síť, soubory) se ověřují; chyby se ošetřují, nepotlačují.
- Nová závislost jen s důvodem a z důvěryhodného zdroje, s pevnou verzí.
- Před commitem projdou kontroly repozitáře (pre-commit, lint, testy), pokud je repozitář má.
- Příkazy, které mažou data, přepisují historii gitu nebo něco nasazují, se spouštějí jen se souhlasem člověka.
- Do logů nepatří odpovědi účastníků ani osobní údaje; e-mail se nikdy nezveřejňuje.

## Testy

- Každá změna chování má test; oprava chyby začíná testem, který chybu ukáže.
- Testy běží přes `make test` / `make quality` a před commitem musí projít.
- Testy nemažeme ani neoslabujeme, aby prošly; přeskočení jen s uvedeným důvodem.
- Testy nezávisí na síti ani na pořadí; v testech nejsou skutečná tajemství.

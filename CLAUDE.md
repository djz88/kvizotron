# Kvízotron — pokyny pro agenty

`AGENTS.md` je symlink na tento soubor.

Typ projektu: self-hosted webová aplikace v Pythonu (Django) — **etapa A, milníky B1, B1.5, B2, B3, B4, B5, B6, C1, C2, C3, C4, C4.5, C5, D1, D2, D3, D4 a D5 hotové: admin UI, kvízy ve třech jazycích, bezpečné změny kvízu za běhu, navigace a vzhled, typy otázek Výběr a Přiřazení, obrázky, bodování a zdroje, banky otázek, režimy průchodu, odhalení odpovědí, obrázky z adresy, náhled, testovací odkazy, import a export otázek, typy Číslo, Text a Fotka, hodnocení fotek, uložené odpovědi, soukromý odkaz na výsledek, veřejný průchod, plán běhu, uzávěrka, časový limit s odpočtem, archivace běhu, účastníci a přístupový kód, profil dat, stav bez ukládání, doba uchování, pokračování v prohlížeči, veřejný žebříček, statistiky a porovnání běhů, zjednodušená administrace, průchod po stránkách, logo, odměny a losování, vlastní název, motto a barvy, export výsledků, mazání dat běhu, žádost o výmaz, správa modulů, limity požadavků, hlavičky, denní záloha a obnova a zátěžový test**
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

Stav: hotová etapa A (milníky A1–A4), B1, B1.5, B2, B3, B4, B5, B6, C1, C2, C3, C4, C4.5, C5, D1, D2, D3, D4 a D5: kernel, provideři, admin UI, hraní kvízu v cs/en/uk s typy Výběr a Přiřazení, nahrávání obrázků, bodování část za část, zdroje u výsledku, QR, skóre na serveru, nastavení s přepsáním u kvízu, přepnutí běžícího kola na novou revizi, přehled změn, návrat ke starší revizi, duplikace a archivace kvízu, popis kvízu, hlavní tlačítko podle stavu, pět sad barev, veřejné menu, banky otázek s losováním bez opakování, míchání, tři režimy průchodu s ukazatelem postupu, odhalení odpovědí, přeložené vysvětlení, obrázky z adresy jako kopie nebo z jejich serveru, nastavení s přepsáním u otázky, náhled bez ukládání, testovací odkazy na vybranou verzi, import otázek z CSV a ZIP a jejich export, typy Číslo, Text a Fotka, hodnocení fotek po otázkách nebo po pokusech, volba ukládání a viditelnosti odpovědí, soukromý odkaz na výsledek, veřejný průchod po skončení běhu, požadavky modulů na nastavení, plán běhu se začátkem a uzávěrkou, časový limit pokusu s odpočtem a automatickým odesláním, archivace běhu, jedno nastavené časové pásmo, pravidla opakování s anonymní cookie jen tam, kde je běh potřebuje, sběr jména a e-mailu před startem nebo na konci, zákaz stejných přezdívek, přístupový kód k běhu uložený jen jako hash a tabulka pokusů u běhu, jeden profil dat u běhu (nic, skóre, odpovědi, podrobně) místo `store_answers`, režim bez ukládání, který po odeslání smaže pokus a započítá ho, doba uchování uložená u běhu a pokračování po obnovení stránky z kopie v prohlížeči, která není delší než 24 hodin, veřejný žebříček běhu (skrytý, během běhu, po skončení) s jedním oficiálním pokusem na prohlížeč, anonymními jmény během běhu, shodami podle ADR-0026, režimy revizí se sloučením a projektorem, statistiky běhu, porovnání běhů a řazení tabulky pokusů, přepínač Základní / Vše se sedmi skupinami nastavení, plán běhu ukazující jen rozdíly, záložky s „Více“, průchod po stránkách N otázek, výchozí průchod po otázce pro nové instalace, logo v liště a na stránce O aplikaci, odměny za práh, účast, ručně a losováním kopírované do běhu ze šablony kvízu nebo z předchozího běhu, nároky z oficiálního pokusu s pokyny k vyzvednutí u výsledku, nastavení více prahů a kontaktu s výherci a ruční losování s náhradníky, posunem, náhradním výhercem a novým losováním v historii, která se nemění, se zveřejněním výherců na žebříčku, vlastní název, motto, logo, barvy a patička globálně s přepsáním po polích u kvízu, barvy dopočítané na WCAG AA a jeden řádek patičky na každé veřejné stránce (text správce, licence, odznaky Python, Django a HTMX, „Běží na Kvízotronu“ s verzí, rok a veřejný kontaktní e-mail, který bez nastavení bere e-mail účtu autora kvízu), volitelný e-mail správce, autor kvízu doplněný i zpětně a panel sekcí na stránkách nastavení s přepínačem Základní / Vše, export výsledků jednoho běhu, všech běhů nebo vybraných běhů do CSV se středníkem a BOM (pokusy, účastníci, statistiky otázek, odpovědi, nároky na odměny a historie losování) po souborech nebo v ZIP s fotkami, připravený vláknem na pozadí a ke stažení 24 hodin jen pro správce, který ho zadal, a kontrakt pro Google Sheets bez implementace, hodinové mazání dat běhu po uplynutí doby uchování ve službě `jobs` po krátkých transakcích s anonymním souhrnem pro statistiky, přesunem do archivu a záznamem bez osobních údajů, běhy už po době zadržené do potvrzení správcem, „Smazat data teď“, žádost o výmaz napříč běhy podle e-mailu (hledání jedním dotazem podle `Participant.email_key`, po výmazu se čistí mezipaměť žebříčku) nebo přezdívky s otiskem e-mailu v záznamu, Historie mazání a datum smazání u běhu, stránka Moduly s přepínáním pluginů, důvody odmítnutí a zámkem pluginů, bez kterých aplikace nefunguje, přehled nastavení modulu s výpisem, kde se hodnota liší od globální, limity požadavků po adrese klienta v pěti koších v paměti procesu (přihlášení: jen neúspěšné, po jménu a adrese a navíc strop po adrese napříč jmény, místo se bere před ověřením hesla a při správném přihlášení se vrací; špatný kód; odeslání; start; 429 s `Retry-After`, každá veřejná routa s POST má v testu koš nebo důvod, ADR-0058), automatické odeslání na konci času, které stránka opakuje po chybě spojení, 5xx a 429 se stejným klíčem (zachrání jen to, co se napraví v rezervě 5 s před koncem; `start` se neopakuje; ADR-0060), HSTS na šest měsíců a testovaná sada hlaviček odpovědí včetně `frame-ancestors 'none'`, Caddy, který zavírá nečinná spojení k aplikaci dřív než gunicorn, denní záloha databáze (zálohovací API SQLite) a médií ze služby `jobs` do svazku `backups`, ověřená a zapsaná na disk před zveřejněním, s mazáním po `KVZ_BACKUP_RETENTION_DAYS` po každém pokusu a nejnovější platnou zálohou vždy ponechanou, ruční obnova `manage.py restore <datum|latest>`, která odmítne poškozenou zálohu, starší schéma, databázi v používání, běžící `app` nebo `jobs` (tep v souboru u databáze mladší než 60 s) i dřívější nedokončenou obnovu (značka `.restoring` v `pre-restore-<čas>`, který `prune` nikdy nesmaže) a staré údaje nechá v `pre-restore-<čas>` (ADR-0059, ADR-0061), viditelný průchod služby `jobs` (záznam začátku, konce a výsledku, healthcheck `python -m app.domain.heartbeat check` a řádek „Poslední průchod“ na Historii mazání, ADR-0061), `manage.py backup`, který při adresáři, který `prune` nesmazal, vypíše počet a skončí chybou, zátěžový test 50 účastníků s fotkami jako vláknový test v `make test` a `make load` se zálohou během odesílání, nácvikem obnovy a zkouškou adres, jediný přehled konfigurace `docs/configuration.md` hlídaný testem a AC-03 až AC-18 pojmenovaná testy, soukromá adresa fotky u výsledku, která při chybném tvaru nic nezaloguje, a žádné osiřelé soubory fotek při chybě ukládání. Po D5 přibyly typy kvízů (ADR-0062, AC-171): sedm pojmenovaných sad nastavení kvízu z pluginu `quiz_types` za portem `quiz_type` (Procvičování, Závěrečný test, Zkouška s opravným pokusem, Zkouška nanečisto, Soutěž o ceny, Hospodský kvíz a Jednoduchý kvíz, který vrátí kvíz ke globálnímu nastavení), volba typu při založení kvízu i později s přehledem změn a potvrzením, lišta s počtem odchylek a značky ▲ u nastavení, které se od typu liší, pravidla střetů nastavení společná pro formuláře i typy (`app/domain/setting_rules.py`) a duplikace kvízu, která kopíruje typ i nastavení kvízu. Přídavky pro testy (projekt B, ADR-0063, AC-172 až AC-175): hranice úspěchu v procentech (výsledek, soukromý odkaz, tabulka pokusů, statistiky, export, žebříček), nejvýš tolik pokusů a zákaz dalších po úspěchu (`ParticipantPolicyPlugin` 1.1), pravidla `last` a `average` pro platný výsledek (`results.kept`) a odhalení odpovědí po uzavření běhu na soukromém odkazu od uzavření plus 10 minut (`attempts.LATE_UPLOAD_WINDOW`). Aplikace je od D5 určena na veřejné nasazení v topologii Compose s Caddy, nebo jako jeden kontejner za ingressem (cíl `single` v `Dockerfile`, `manage.py serve`, ADR-0066), vždy s jedním procesem aplikace (limity berou N-tou adresu `X-Forwarded-For` zprava podle `KVZ_TRUSTED_PROXIES`, a počítají v paměti procesu; HSTS a strop těla požadavku drží i aplikace). Před verzí 1.0 už nezbývá žádný milník: zbývají kontroly vydání z `docs/deployment.md` (`make quality`, `make smoke`, `make load`, nácvik obnovy, průchod v prohlížeči) a třídění technického dluhu, které uživatel odložil na dobu po D5 (`docs/_architecture/TECH_DEBT.md`); `make smoke` a `make load` čekají po startu asi o minutu déle, protože healthcheck služby `jobs` poprvé proběhne po minutě.

## Příkazy

Funguje teď:

- `make help` — seznam cílů
- `make hooks` — nainstaluje git hooky (pinnutý pre-commit) pro commit, zprávu commitu a push
- `make private-traces` — založí prázdný `.git/info/private-traces` pro osobní slova, která hooky odmítnou; existující nechá
- `make env-update` — nainstaluje verze, které projekt deklaruje: uv (`[tool.uv] required-version`), Python a balíčky (`uv.lock`), pre-commit s hooky, Docker image; nic nepovyšuje nad to; `make doctor` na něj odkáže
- `make setup` — nainstaluje závislosti; vyžaduje uv ve verzi z `pyproject.toml` (`make env-update`)
- `make setup-reset` — `make clean` a `make setup`; verze bere z `uv.lock`, nepovyšuje je
- `make doctor` — ověří nástroje (uv, docker, hooky)
- `make clean` — smaže build prostředí (`.venv`, cache nástrojů, výstupy buildu); `.env`, data, zálohy ani worktree se nemažou
- `make lint` — ruff a mypy; `make lint fix` opraví, co jde
- `make test` — pytest
- `make secrets` — gitleaks ve staged změnách a v historii gitu; soubory mimo git nekontroluje
- `make quality` — lint, testy, gitleaks a kontrola `TECH_DEBT.md`; totéž běží v CI
- `make smoke` — spustí nasazení v Dockeru a ověří ho
- `make load` — zátěž v Dockeru: 50 účastníků odešle fotky naráz při záloze, obnova ze zálohy a zkouška adres (projekt `kvizotron-load`, minuty; do `make quality` nepatří)
- `make wiring` — jen kontroly napojení (`tests/test_wiring.py`); běží i v `make test`
- `make plan-check plan=… base=main` — změnily se soubory, které plán jmenuje?
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
- Nové nastavení se dědí global → kvíz → otázka, užší rozsah musí mít napsaný důvod (ADR-0042). Každý modul uvádí pole `settings` v manifestu, a pokud žádné nemá, tak `[]`; bez toho testy neprojdou. Kam nastavení patří, rozhoduje ten, kdo ho přidává: agent se zeptá uživatele, pokud to zadání neříká. Postup je ve skillu `kvizotron-add-setting`.

## Profil pro dev-workflow

Profil: `kvizotron`. Zpřísňuje klasifikaci skillu `dev-workflow`; agent ho čte odsud, nic ho nevymáhá.

- Vždy VELKÁ: `app/contracts/`, `app/kernel/`, `app/domain/models.py` a migrace, `manifest.py` modulů, `app/providers/auth_local/`, `deploy/compose.yaml`.
- Aspoň STŘEDNÍ: `app/api/play.py`, `app/api/run_clock.py`, `app/domain/attempts.py`, `app/domain/tokens.py`. Řídí, co se přijme a jak se počítá čas a skóre.
- Vždy VELKÁ je i změna, která se dotkne UI a domény zároveň, nebo mění chování popsané v ADR.

## Skilly projektu

V `.claude/skills/`: `kvizotron-milestone` (návrh a uzavření milníku), `kvizotron-add-setting` (nové nastavení), `kvizotron-add-module` (nový plugin nebo provider), `kvizotron-browser-walkthrough` (průchod v prohlížeči a stack `kvizotron-browser`), `kvizotron-check-applied` (je všechno použité a napojené, před `review-roles`), `kvizotron-check-integration` (toky napříč vrstvami). Skilly tohoto repozitáře se jmenují `kvizotron-*`; hlídá to `tests/test_docs.py`. Profil pro `review-roles` je `.claude/review-profile.md`.

## Pravidla

- Do kódu, konfigurace, logů ani commitů nepatří tajné údaje (hesla, tokeny, klíče); patří do proměnných prostředí nebo do správce tajných údajů.
- Vstupy zvenčí (uživatel, síť, soubory) se ověřují; chyby se ošetřují, nepotlačují.
- Nová závislost jen s důvodem a z důvěryhodného zdroje, s pevnou verzí.
- Před commitem projdou kontroly repozitáře (pre-commit, lint, testy), pokud je repozitář má.
- Příkazy, které mažou data, přepisují historii gitu nebo něco nasazují, se spouštějí jen se souhlasem člověka. Hook `.claude/hooks/guard_docker_volumes.py` odmítá mazání svazků stacku `kvizotron-browser` a stacku bez jména, u jiných se ptá.
- Do logů nepatří odpovědi účastníků ani osobní údaje; e-mail se nikdy nezveřejňuje.
- Zprávy commitů nemají řádek `Claude-Session` ani jiný odkaz na sezení agenta; `Co-Authored-By` zůstává. Dokumentace, plány a soubory agenta (`docs/`, `.claude/`, `CLAUDE.md`) neobsahují lokální cesty (domovský adresář, dočasné adresáře agenta) ani adresy z vlastní sítě: místo nich `<repo>`, `<scratchpad>` a ukázková adresa jako `192.168.1.10:8443`. Cesty a odkazy hlídá `tests/test_docs.py`; commit, zprávu commitu a push hlídá `tools/private_traces.py` (hooky z `make hooks`), který bere i osobní slova z `.git/info/private-traces` mimo git.

## Testy

- Každá změna chování má test; oprava chyby začíná testem, který chybu ukáže.
- Testy běží přes `make test` / `make quality` a před commitem musí projít.
- Testy nemažeme ani neoslabujeme, aby prošly; přeskočení jen s uvedeným důvodem.
- Testy nezávisí na síti ani na pořadí; v testech nejsou skutečná tajemství.

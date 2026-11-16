# Kvízotron — analýza repozitáře, 2026-11-16

## 1. Stav vůči roadmapě

Hotovo (podle `docs/_architecture/roadmap.md` a ověřeno testy): etapy A–D, milníky A1–A4, B1–B6, C1–C5, C4.5, D1–D5, dodatek Typy kvízů (ADR-0062) a projekt B „přídavky pro testy“ (ADR-0063). 176 AC definováno, žádný milník neschází.

Ověření dnes: `make lint` OK (ruff, mypy 201 souborů), `make test` 5480 passed, 4 skipped (3:48 min), `make smoke` OK (všechny kontroly PASS, exit 0).

Co před 1.0 zbývá (roadmapa i CLAUDE.md to říkají stejně):
- Kontroly vydání: `make load`, nácvik obnovy, průchod v prohlížeči (tento dokument ho částečně pokrývá).
- TD-008: CI nikdy neběžela na GitHubu. Release gate je neprokázaný.
- Třídění technického dluhu: 70 OPEN položek v `TECH_DEBT.md`.
- Mimo rozsah 1.0 (LATER): Google Sheets, video otázka, další témata, SSO, e-mail, vouchery, JSON export.

Nesrovnalosti v repozitáři:
- Pracovní strom má 42 změněných `.mo` souborů bez obsahové změny; `make messages` je generuje nedeterministicky (časové razítko). Strom je trvale „dirty“.
- Nesledované soubory v kořeni: `report.md`, `kvizotron_v4/`, `tmp-old/` (9 MB), `.superpowers/`, `kviz_eu_cr_*`, `kv_z_17_*`. Patří do `.gitignore` nebo pryč.

## 2. Průchod v prohlížeči

Postup: samostatný stack `kvizotron-review` (porty 28080/28443, čisté svazky, admin `review`), Playwright + Chromium headless. Pohledy: admin 1280 px světlý cs; účastník 390 px tmavý uk; klávesnice 1280 px cs. Vytvořen kvíz `rev-walk` se 3 otázkami (výběr, číslo, přiřazení), publikován, spuštěn, odehrán, žebříček zapnut, běh ukončen. Stack `kvizotron-browser` zůstal nedotčen (přebuildován z aktuálního kódu, ale přihlášení vypršelo).

Prošlo bez chyby: založení kvízu, editor tří typů otázek, přehled změn, start, průchod po otázkách s ukazatelem, odeslání, výsledek, žebříček (veřejný, projektor, telefon), uzavření běhu, stránky Běhy/Hodnocení/Testovací odkazy/Revize/Odměny/Export/Banky/Správci/Historie mazání/Import/Moduly/Náhled. Konzole bez JS chyb, žádná 5xx.

Nálezy (účastník):
- P1 Klávesnice: po „Začít“ ztratí stránka fokus (activeElement = body, Tab skáče do patičky). Po „Další“ fokus správně na sekci otázky. Oprava: po HTMX swapu zaměřit nadpis „Otázka 1 z N“ (`tabindex=-1`, `focus()`).
- P2 Odeslání bez odpovědí projde bez varování (výsledek 1/3). Oprava: před odesláním potvrzení „N otázek bez odpovědi“.
- P3 Stránka kvízu s ukončeným během vrací HTTP 404 (`public.py:169`). Prohlížeč to loguje jako chybu, sdílené odkazy a monitoring to vidí jako neexistující stránku. Zvážit 200 (nebo 410).
- P4 Žebříček na telefonu se rozpadá na dvojice „Místo 1. / Jméno Hráč 2 / Body 3/3“, každý řádek tabulky je karta. U 50 účastníků nepřehledné. Oprava: kompaktní řádek „1. Hráč 2 · 3/3 · 100 %“.
- P5 Výsledek bez žebříčku nabízí jen „Zpět na kvízy“. Chybí „Zobrazit odpovědi“ (když je odhalení povoleno) a vysvětlení, proč není víc.

Nálezy (admin):
- A1 „Ukončit běh“ existuje dvakrát: tlačítko v hlavičce jde přes potvrzení (`run_close` GET), formulář dole na stránce běhu (`run.html:193`) ukončí běh okamžitě bez potvrzení. Sjednotit na potvrzení.
- A2 Nový kvíz: „Identifikátor v adrese“ je povinný a bez nápovědy, nic se nepředvyplní z názvu; jazyky jsou všechny odškrtnuté a popsané kódy `cs/en/uk`; „Typ kvízu“ sbalený. Oprava: slug odvodit z názvu, výchozí jazyk zaškrtnout, názvy jazyků, typ rozbalený (je to nejdůležitější volba).
- A3 Přehled změn při první publikaci vypisuje každé pole s „Před –“ (3 otázky = 4 obrazovky). Pro první revizi stačí souhrn „3 otázky, 3 body, jazyky cs, uk“.
- A4 Stránka běhu měří 4300 px: QR, odměny, žebříček (10 selectů), statistiky, účastníci, pokusy, export, uzávěrka, čas. Pole „Uzávěrka“ sedí pod nadpisem „Export“. Tři různá tlačítka Uložit. Panel „Sekce“ pomáhá, ale záložky by byly čitelnější.
- A5 Nastavení kvízu měří 6500 px, tři nezávislé formuláře se třemi „Uložit“; select „Typ kvízu“ ukazuje „Procvičování“ i u kvízu bez typu (vypadá jako zvolený typ).
- A6 Formuláře otázek: 6 řádků možností × (cs, uk, obrázek, adresa, popis ×2) = 48 polí najednou. Obrázek k možnosti schovat za „Přidat obrázek“.
- A7 Stránka Moduly: u pluginu, bez kterého aplikace nefunguje, je text „Aplikace bez modulu scoring.basic nefunguje“ místo tlačítka. Lepší zamčené tlačítko s tooltipem.
- A8 Chybějící CSRF na `start` a `resume` (`play.py:317, 376`, `csrf_exempt`). Záměr (účastník bez session), ale cizí stránka může zahájit pokus v cizím prohlížeči. Nízké riziko, zdokumentovat v `security.md`.

## 3. Code review — chyby

Vyvráceno: oba agenti hlásili obejití limitů přes spoofovaný `X-Forwarded-For`. Empirický test na stacku: 6. pokus s jinou XFF dostal 429. Caddy nedůvěryhodnou XFF zahazuje. Doporučení: přidat tento test do `deploy/smoke.sh`, aby to zůstalo pravda.

Potvrzené (seřazeno podle dopadu):
1. `app/api/play.py:196-201, 448-459` — `allow()` a `record()` jako dvě oddělené akce, souběžné požadavky z jedné adresy projdou nad limit. `rate_limit.try_acquire` už existuje a používá ho login. Použít i tady.
2. `app/api/admin_quizzes.py:690-745` — `quiz_publish(start=1)` a `run_open` nechytají `results.ResultConflict`, `rewards.RewardConflict`, `RequirementUnmet` → HTTP 500 místo vysvětlení. `admin_runs.py:308, 372` to dělá správně. Sdílený mapovač chyb otevření běhu.
3. Archivovaný kvíz není jen ke čtení (`domain.md:110` to slibuje): `admin_rewards.py:460, 486, 624`, `admin_grading.py:298, 321, 342`, `admin_runs.py:501, 617, 839` nemají `ensure_editable`. Lze losovat, rušit nároky, měnit známky na archivovaném kvízu. Jedna kontrola v doménových vstupech.
4. `app/domain/attempts.py:759` — `events.emit("attempt.submitted")` běží uvnitř atomic bloku s `with_retry`; při „database is locked“ se blok opakuje a událost odejde dvakrát. Použít `transaction.on_commit`.
5. `app/domain/rewards.py:646-672` — `grant_manual` neověřuje odeslaný pokus; pouze UI seznam. Ručně sestavený POST přidělí odměnu účastníkovi bez pokusu.
6. `app/api/admin_settings.py:20-23`, `admin_forms.py:894-917` — ukládání globálních nastavení a brandingu po jednotlivých transakcích; chyba uprostřed nechá polovinu uloženou a formulář hlásí chybu. Obalit `transaction.atomic`.
7. `app/domain/authoring.py:660`, `admin_quizzes.py:318` — `quiz.save()` celého objektu přepíše `archived_at` a `quiz_type` zastaralou hodnotou při souběhu dvou správců. `save(update_fields=...)` jako v `quiz_types.py:213`.
8. `app/domain/heartbeat.py:132-151` — `jobs_healthy()` ignoruje stáří tepu `jobs` a poškozený záznam průchodu bere jako zdravý. Healthcheck služby může lhát.
9. `deploy/compose.yaml:33-53` — chybí `stop_grace_period`; Docker zabije `app` po 10 s, gunicorn má graceful 30 s, `jobs` může běžet zálohu (souvisí s TD-072).
10. `app/settings.py:18` — `SECRET_KEY` přijme libovolný neprázdný řetězec („x“). Odmítnout krátké hodnoty.
11. `app/api/admin_users.py:133-146` — změna e-mailu neznámého správce tiše uspěje (update vrátí 0).
12. `app/domain/results.py:348-362` — anonymní čísla „Účastník N“ se počítají z živých řádků; výmaz jednoho účastníka přečísluje ostatní. Docstring tvrdí opak. Uložit číslo při vzniku.
13. `app/domain/attempts.py:455-482` — `_replacement` při přepnutí revize nevolá `_require_modules`; s vypnutým pluginem vznikne pokus, který pak dává 503.

Pravděpodobné (ověřit testem):
- `app/kernel/lifecycle.py:84-99` — `blockers()` mimo transakci, souběžné otevření běhu a vypnutí pluginu.
- `app/domain/authoring.py:556` — `ensure_editable` před atomic blokem, souběžná archivace.
- `app/providers/media_local/remote.py:45-49` — NAT64 prefix `64:ff9b::/96` neblokován (jen na NAT64 sítích).
- `app/api/run_clock.py:23-27` — `settle()` na každém požadavku; u zadrženého plánu několik dotazů navíc na každém požadavku.

Výkon (potvrzené N+1, při 50 účastnících nebolí, u desítek kvízů ano):
- Seznam kvízů: ~10 dotazů na kvíz a plné načtení banky pro každý los (`quiz_state.py:69-88`, `banks.py:239-246`).
- Editor: na každý řádek losu dotaz na složku a celá banka (`admin_quizzes.py:163-175`).
- `results.place_of` přepočítává celé pořadí bez cache při každém odeslání (`results.py:631-645`); tabulka má cache 5 s, místo ne.
- `participants.begin()` běží až 3× na jeden start (`play.py:87`, `attempts.py:221`).
- `registry.keys()` dělá dotaz na `is_enabled()` na každý port (`registry.py:56-58`) a `ModuleGateMiddleware` dotaz na každý požadavek.
- Export kvízu/banky s obrázky skládá ZIP v paměti v požadavku (`admin_export.py:41-58`); export výsledků má job na pozadí.

## 4. Code review — zjednodušení

- Duplicitní pomocníci napříč `admin_*.py`: `_admin` (3×), `_uuid` (2×), `_plain` (2×), `_refusal` (4×), `_locale` (2×), `_back` (3×), potvrzovací stránka inline 7×. Jeden modul `admin_common.py`.
- Chůze po řetězu `replaced_by` napsaná 4× (`attempts.py` ~141, ~286, 784; `participants.py:161`). Jeden `_current_of()`.
- `StartedAttempt(...)` stavěno 3× (`attempts.py:152, 260, 281`).
- `needs_participant` / `begin` / `start_decision` / `can_resume` — čtyři obaly jednoho rozhodnutí; nechat `begin`.
- `results.kept()` volané 4× v jednom požadavku (pass_mark, rewards.refresh, played_result, begin); memoizovat.
- Lokální importy kvůli cyklům (`participants.py:111, 170, 242, 289`; `attempts.py:177`; `draws`↔`rewards` TD-049) — známka špatného řezu vrstev.
- Dvě paralelní tabulky umístění nastavení: `admin_forms.BRANDING_PLACES/COLOUR_PLACES` vs. `admin_view.CHILD_OF/COLUMNS`.
- Dlouhé funkce: `quiz_types._plan` (79 ř.), `admin_banks._bank_page` (73), `admin_runs._run_context` (72), `admin_forms.__init__` (62). Soubory nad 800 řádků: `admin_forms.py` 1162, `play.py` 936, `admin_runs.py` 861, `authoring.py` 849.
- Kernel zná slovník kvízu: pevný seznam událostí (`kernel/events.py:12-21`) a regex rout na upload (`kernel/middleware.py:10-16`). Podle `app/kernel/CLAUDE.md` nemá. Registrovat z modulů.
- Kontrakty: `runtime_checkable` Protocol kontroluje jen jména členů (`registry.py:29`); špatná arita projde. `ExporterProvider.write` bere bytes, `ResultsExporterProvider.write` cesty. Sjednotit.
- Testy: 274 souborů, 50 212 řádků, ~3 670 testů; 18 souborů nad 500 řádků (`test_restore.py` 964, `test_choice.py` 953); ~28 duplicitních pomocníků (`a_run`, `who`, `finish`, `make_quiz`); `conftest.py:18` zapisuje do `registry._ports` přímo; `events._handlers` a `lifecycle._usage_checks` se mezi testy neresetují; 4 testy závislé na čase (`test_jobs_heartbeat.py:171`, `test_login_limit.py:118`).

## 5. Provoz a vydání

- Compose: bez `read_only`, `cap_drop`, `pids_limit`, `mem_limit`, limitu logů; secret jako env (vidí `docker inspect`) místo `secrets:`.
- CI: bez `timeout-minutes`, `concurrency`, auditu závislostí (`pip-audit`/`uv audit`), skenu image. Dependabot jen otevírá PR.
- `Makefile:63` `make secrets` s `--all-files` na hooku, který stejně čte jen staged změny. Smazat flag nebo opravit text.
- `settings.py:110` tvrdí, že uploady zůstávají v paměti do limitu těla; Django nad 16 MB spooluje na disk kontejneru. Opravit komentář nebo `TMPDIR`.
- Zálohy jen v lokálním svazku, nešifrované; off-host kopie je v `deployment.md` jen doporučení.
- Překlady: `app/api/locale/uk` má 306 nepřeložených řetězců (admin UI je záměrně jen cs/en; veřejné stránky v uk byly přeložené celé). Zapsat záměr do docs nebo katalog ořezat.

## 6. Doporučené pořadí před 1.0

1. Rozjet CI na GitHubu (TD-008), přidat XFF test do smoke.
2. Opravit body 1–8 z části 3 (každý začít testem).
3. UX: A1, A2, P1, P2 — malé změny s velkým dopadem na první dojem.
4. Rozhodnout TD-101 a TD-036 (živé čtení nastavení otevřeným během) — ohrožují férovost soutěže.
5. Úklid: `.mo` deterministicky nebo mimo git, nesledované soubory, `admin_common.py`, rozdělení `admin_forms.py` a `play.py`.
6. `make load` a nácvik obnovy podle `deployment.md`.

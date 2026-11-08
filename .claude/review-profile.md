# Review profil

## Profil: `kvizotron`

### Kde co je

| Co | Kde |
|---|---|
| Architektura a rozhodnutí | `docs/_architecture/`, `docs/_architecture/adr/` |
| Kontrakty mezi moduly | `app/contracts/`, `docs/_architecture/modules/contracts.md`, `docs/plugin-api.md` |
| Dokumentace | `docs/_architecture/README.md` (mapa `FR-xx`), `docs/_architecture/acceptance-criteria.md` |
| Testy | `tests/`, sdílené sady v `tests/contracts/` |
| Sdílený kód / kernel | `app/kernel/` |
| Konfigurace prostředí | `deploy/compose.yaml`, `deploy/.env.example` |

### Co už je ověřené strojově

Výstup skillu `kvizotron-check-applied` přijde jako vstup, pokud ho volající předá. Nekontroluj znovu, co hlídají `tests/test_wiring.py` a `tests/test_docs.py`: že modul, šablona, adresa, skript nebo ID existují a jsou napojené. Hodnoť, jestli je to správně, ne jestli to existuje.

### Moduly a jejich hranice

| Modul | Vlastní | Nesmí |
|---|---|---|
| `app/contracts` | protokoly a schémata | importovat Django |
| `app/kernel` | bootstrap, registr, události, životní cyklus | obsahovat funkce produktu |
| `app/domain` | kvízy, běhy, pokusy, skóre | importovat `app/api` nebo moduly |
| `app/api` | adresy, šablony administrace a hraní | počítat skóre |
| `app/plugins` | typy otázek, bodování, režimy, téma | importovat cokoli kromě `app.contracts` a `app.kernel`; skládat HTML ručně |
| `app/providers` | přihlášení, databáze, média, CSV | importovat `app/domain`, `app/api`, `app/plugins` |

### Závazná rozhodnutí

- ADR-0006: publikovaná revize je neměnná → `docs/_architecture/adr/0006-separate-quiz-revision-run-attempt-immutable-revisions.md`
- ADR-0007: restart vytvoří nový běh a nepřebírá výsledky → `docs/_architecture/adr/0007-restart-creates-new-run-keeps-history.md`
- ADR-0009: skóre počítá server, klientovi se nevěří → `docs/_architecture/adr/0009-server-authoritative-scoring-signed-token-idempotent-submit.md`
- ADR-0025: o čase rozhoduje příjem na serveru, celé sekundy, `<=` → `docs/_architecture/adr/0025-deadline-boundary-second-semantics.md`
- ADR-0042: nastavení se dědí global → kvíz → otázka, užší rozsah má napsaný důvod → `docs/_architecture/adr/0042-settings-inherited-and-declared.md`
- ADR-0048: stav běhu se mění až při prvním požadavku po termínu → `docs/_architecture/adr/0048-run-timing.md`

### Kritické cesty

- `app/api/play.py`, `app/domain/attempts.py`: co se přijme od účastníka a jak se počítá skóre
- `app/domain/tokens.py`: podepsané tokeny pokusu a výsledku
- `app/domain/run_schedule.py`, `app/api/run_clock.py`: otevření a uzavření běhu
- `app/domain/visibility.py`: kdo vidí odpovědi a fotky
- `app/api/admin_auth.py`, `app/providers/auth_local/`: přihlášení správců
- `app/providers/media_local/`: nahrané soubory a stahování z adres
- `deploy/compose.yaml`, `deploy/Caddyfile`: nasazení

### Co je v tomhle projektu BLOCKER

- Klíč odpovědí ve výstupu `public_payload()`, `render_public` nebo na stránce před odesláním.
- Skóre, řešení nebo čas převzatý od klienta.
- Změna publikované revize, nebo nový běh, který přebírá výsledky.
- Odpověď účastníka, osobní údaj nebo tajný údaj v logu; e-mail ve veřejném výstupu.
- Odeslání přijaté po `min(deadline_at, started_at + limit)`.
- Test nebo náhled, který se započítá do výsledků.
- Nové chování bez testu, nebo oslabený test.

### Testovací očekávání

- Každá změna chování má test, oprava chyby začíná testem, který ji ukáže.
- Každý modul projde sadou v `tests/contracts/`; výjimka je jen v `tests/test_wiring.py` s položkou dluhu.
- Scénáře, které musí zůstat pokryté: `docs/_architecture/acceptance-criteria.md`.

### Konvence, které nejsou vidět z kódu

- Bezpečnost je přiměřená kvízu: pro vstupy od důvěryhodného správce stačí základní kontrola, antivirus ani sanitizéry se nenavrhují.
- `QuizRun` je v textech běh, nikdy kolo. Dokumentace je anglicky, `CLAUDE.md` česky.
- `.mo` soubory jsou v gitu záměrně.
- Odložené drobnosti patří do `docs/_architecture/TECH_DEBT.md`, ne do oprav mimo rozsah.

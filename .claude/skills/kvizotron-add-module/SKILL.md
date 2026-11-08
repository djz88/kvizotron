---
name: kvizotron-add-module
description: Use when adding a new Kvízotron plugin or provider, a new question type, scoring strategy, theme or infrastructure backend, or when a feature would otherwise go into the kernel.
---

# Nový modul

Funkce patří do modulu za kontraktem (ADR-0037). Vzory, které běží a testy je hlídají:

| Co stavíš | Opiš z |
|---|---|
| Typ otázky | `app/plugins/questions/number/` |
| Modul mimo tento repozitář | `tests/fixtures/demo_site/kvz_demo_question/` |
| Provider | `app/providers/csv_io/` |

## 1. Než začneš

- **Plugin, nebo provider?** Funkce, které se zapínají za běhu, jsou plugin. Infrastruktura vybraná při startu je provider.
- **Existuje port?** Protokoly jsou v `app/contracts/`. Nový port je rozhodnutí: potřebuje ADR a sdílenou sadu v `tests/contracts/`.
- **Má vlastní nastavení?** **REQUIRED SUB-SKILL:** `kvizotron-add-setting`. Bez nastavení se v manifestu uvádí `"settings": []`.

## 2. Soubory

V adresáři modulu:

- `manifest.py` bez importu Djanga: běží, když se načítá konfigurace. `id`, `kind`, `version`, `app`, `api_compatibility`, `provides`, `requires`, `settings`.
- `apps.py`: v `ready()` volá `registry.register(<port>, <klíč>, <objekt>, <id modulu>)`. Čtvrtý argument je `id` z manifestu.
- Šablony v `jinja2/<název>/`, texty v `locale/`.
- Importuje jen `app.contracts` a `app.kernel`. Pluginy jsou mezi sebou neviditelné.

## 3. Napojení

Každý bod hlídá test v `tests/test_wiring.py`:

1. Řádek v `[project.entry-points."kvizotron.modules"]` v `pyproject.toml`. Potom `make setup`, jinak prostředí modul nevidí.
2. Má-li texty: adresář v `ROOTS` v `tools/messages.py`, potom `make messages` a vyplněné `msgstr` v cs i uk.
3. Sdílená sada v `tests/contracts/`. Typ otázky má `test_<typ>.py`, který dědí `QuestionTypeContract`.
4. Dokument: `docs/_architecture/plugins/` nebo `providers/` se jménem modulu, typ otázky v `docs/_architecture/plugins/question-types.md`.
5. Nové požadavky a rozhodnutí: mapa `FR-xx` v `docs/_architecture/README.md`, případně ADR.

## 4. Na co test nepřijde

- `describe_definition` musí změnit výstup při změně každého pole definice, jinak ji přehled změn neukáže. Totéž platí pro nové pole později.
- Nový typ otázky mění počet v `tests/contracts/test_demo_question.py`, když přidáš test do `tests/contracts/question_type.py`.
- Vypnutí pluginu za běhu: stará revize s jeho otázkami se musí dát dál vyhodnotit (`include_disabled`).
- Vlastní tabulky mají migraci v modulu. Tabulky domény se neupravují.

## 5. Hotovo

**REQUIRED SUB-SKILL:** `kvizotron-check-applied`.

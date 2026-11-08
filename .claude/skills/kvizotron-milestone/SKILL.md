---
name: kvizotron-milestone
description: Use when starting, designing, planning or closing a roadmap milestone of Kvízotron (A1 to D5), including "co je další krok", "pokračuj" or "spusť brainstorming" when the next step is a milestone.
---

# Milník Kvízotronu

Doplňuje obecné skilly `superpowers:*` o to, jak se milníky dělají tady. Pořadí: návrh → plán → stavba → ověření → dokumenty → merge. Každý krok začíná až po souhlasu s předchozím.

## 1. Návrh

Nejdřív si přečti řádek milníku v `docs/_architecture/roadmap.md` a jeho `FR-xx`, ADR a `OQ-xx`. Na to, co je tam rozhodnuté, se neptej. ADR se statusem `proposed` rozhoduje člověk.

Pak **REQUIRED SUB-SKILL:** `superpowers:brainstorming`, s těmito pravidly:

- Otázky přes `AskUserQuestion`, doporučená volba první, s krátkým příkladem, co která volba znamená.
- Poznámka u odpovědi je rozhodnutí, i když se liší od nabídky. Když z ní nejde poznat volba, polož jednu krátkou otázku.
- Holé „ano“ není přeskočení otázek. Bez otázek se staví až po výslovném „bez otázek“ nebo „rovnou“.
- Bezpečnost přiměřená kvízu: nejjednodušší mechanismus, který zastaví reálné podvádění.
- Nové nastavení: **REQUIRED SUB-SKILL:** `kvizotron-add-setting`.

## 2. Spec

Soubor v `docs/superpowers/specs/` se jménem `RRRR-MM-DD-<milník>-<téma>-design.md`, anglicky, s oddíly v tomto pořadí: Why, Goals, Non-goals, Anti-goals, Behaviour, Constraints, Risks, Left to the builder, Verification.

Každé rozhodnutí má značku: **[user]** řekl uživatel, **[docs]** už je v `docs/_architecture`, **[call]** tvoje volba, kterou může opravit. Domněnka nikdy nedostane **[user]**.

Po schválení specu **REQUIRED SUB-SKILL:** `superpowers:writing-plans`. Větev `feat/<milník>-<téma>`, způsob stavby volí uživatel.

## 3. Ověření před předáním

Všechno na sloučeném stromu, výsledek hlas s výstupem:

1. `make quality`
2. `make smoke`. Když běží `kvizotron-browser`, s `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543`.
3. **REQUIRED SUB-SKILL:** `kvizotron-browser-walkthrough`, pokud se změnilo cokoli, co uvidí člověk.
4. **REQUIRED SUB-SKILL:** `kvizotron-check-applied`.
5. Závěrečná kontrola celé větve čerstvým recenzentem, s výstupem z předchozího kroku. Nálezy Critical a Important oprav testem, který nejdřív selže.

## 4. Dokumenty milníku

Každý bod projdi, i když se nakonec nezmění:

| Místo | Co |
|---|---|
| `docs/_architecture/roadmap.md` | řádek milníku, jeho AC a `Done RRRR-MM-DD` |
| `docs/_architecture/acceptance-criteria.md` | nová AC od dalšího volného čísla; test je musí jmenovat, jinak spadne `tests/test_docs.py` |
| `docs/_architecture/adr/README.md` | nové ADR a jeho řádek |
| `docs/_architecture/modules/api-ui.md` | adresy a tabulka „Where things are set“ |
| `docs/_architecture/modules/domain.md`, `docs/_architecture/data-model.md` | stavy a tabulky |
| `CLAUDE.md` | seznam milníků v úvodu, odstavec Stav a „Další je …“ |
| `CLAUDE.md` v dotčených adresářích | co v nich přibylo a na co si dát pozor |
| `.claude/skills/kvizotron-check-integration/flows.md` | nový tok nebo článek |

Odložené drobnosti se zapisují přes `make tech-debt-create title="…"`, ne ručně, a uživatel je vidí v závěrečné zprávě.

## 5. Předání

Rozhodnutí, která jsi udělal za uživatele, a odložené drobnosti vypiš celé. Na konci nabídni možnosti ze `superpowers:finishing-a-development-branch` a čekej. Merge, push a mazání větví dělá až souhlas; repozitář nemá remote.

Do `kvizotron-browser` se nesahá jinak, než říká `kvizotron-browser-walkthrough`.

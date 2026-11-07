# Modul: app/contracts

Rozhraní mezi kernelem a moduly. Jeden soubor, jen typy: `Protocol`, dataclassy a konstanty. Žádná implementace.

## Odpovědnosti

- Protokoly `QuestionTypePlugin`, `ScoringStrategyPlugin`, `ThemePlugin`, `QuizFlowPlugin`, `AuthenticationProvider`, `PersistenceProvider`, `MediaStorageProvider`.
- Datové typy `ItemGrade`, `ScoreBreakdown`, `DefinitionRow`, `AdminFormError`, `ImageRefused`, `StoredImage`.
- `PORTS`: která schopnost má který protokol. `EXACTLY_ONE`, `REQUIRED_CAPABILITIES`.

## Zakázáno

- Importovat Django nebo cokoli z `app.`: toto je jediný balíček, na kterém všichni závisejí.
- Měnit protokol bez sdílené sady v `tests/contracts/` a bez `docs/plugin-api.md`.

## Veřejné API

Všechno v `__init__.py`. Popis pro autory modulů je v `docs/plugin-api.md`.

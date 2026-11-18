# Module: app/contracts

The interface between the kernel and the modules. One file, types only: `Protocol`, dataclasses and constants. No implementation.

## Responsibilities

- Protocols `QuestionTypePlugin`, `ScoringStrategyPlugin`, `ThemePlugin`, `QuizFlowPlugin`, `QuizTypePlugin` (port `quiz_type`, only definitions of settings sets, ADR-0062), `AuthenticationProvider`, `PersistenceProvider`, `MediaStorageProvider`, `ResultsExporterProvider` (port `results_exporter`), `TableSinkProvider` (port `table_sink`, a contract for Google Sheets without an implementation, ADR-0055) and `RetentionProvider` (port `retention`).
- Data types `ItemGrade`, `ScoreBreakdown`, `DefinitionRow`, `AdminFormError`, `ImageRefused`, `StoredImage`, `ExportTable`, `ExportJobView`, `RetentionRecord`, the exception `ExportJobGone`.
- `PORTS`: which capability has which protocol. `EXACTLY_ONE`, `REQUIRED_CAPABILITIES`.

## Forbidden

- Importing Django or anything from `app.`: this is the one package everyone depends on.
- Changing a protocol without a shared suite in `tests/contracts/` and without `docs/plugin-api.md`.

## Public API

Everything in `__init__.py`. The description for module authors is in `docs/plugin-api.md`.

---
status: accepted
date: 2026-11-05
---

# ADR-0032: Import and export formats

## Context and Problem Statement

FR-41 requires a defined CSV schema and/or JSON in a CSV field, without exact columns. Import and export
must be reasonably human-friendly: a person should see the basics in a spreadsheet. Only the full
output has to be machine-oriented, for example for processing by an LLM.

## Decision Drivers

* People can read exports and write questions in a spreadsheet
* Full export can be imported back
* New question types need no schema change
* Answer keys are not exposed in the overview

## Considered Options

* Human overview CSV plus one full CSV shared by export and import; JSON export later as a module
* Full output as JSON only, with a simple CSV import
* All data in a single CSV format

## Decision Outcome

Chosen option: "Human overview CSV plus one full CSV shared by export and import; JSON export later as
a module", because it meets the spec, stays usable in a spreadsheet and needs one exchange format.

| Output | Audience | Content | Import |
|---|---|---|---|
| Overview CSV | People | Rank, nickname, score, right/wrong per question; question order and text. No answer keys, no e-mails | No |
| Full CSV | Admins, machines | Everything, including answer keys | Yes |
| JSON (LATER) | Machines, LLM | Full content; delivered as a separate `ExporterProvider` module | No |

Full CSV example:

```text
schema_version,type,points,text_cs,text_uk,option_1_cs,option_2_cs,correct,config_json
```

Rules:

* One row is one question. Texts use one column per locale.
* Choice types use plain option columns; the question-type plugin defines its columns.
* Complex types (for example ordering or matching) use `config_json`.
* Quiz-level settings are in a separate CSV file.
* A sample CSV is available for download.

### Consequences

* Good, because common questions can be written without JSON
* Good, because an exported quiz can be edited and imported back
* Bad, because the import handles two kinds of columns and has many columns with three locales
* Bad, because right/wrong per question exists only if individual answers are stored
* Bad, because JSON inside CSV is not ideal for machines until the JSON module exists

### Confirmation

Round-trip test: export followed by import gives the same quiz. [AC-13](../acceptance-criteria.md).

## More Information

Resolves [OQ-11](../open-questions.md). Refines [ADR-0019](0019-csv-import-export-json-in-field-draft-output.md).
Exact column names are finalised with the plugins in Stage B.

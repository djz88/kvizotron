---
status: accepted
date: 2026-11-04
---

# ADR-0019: CSV import/export with JSON-in-field for complex structures; import creates drafts

## Context and Problem Statement

Authors want bulk content exchange via spreadsheets; Google Sheets integration is deferred.

## Decision Drivers

* Spreadsheet friendliness
* Safety (formula injection)
* No accidental publication

## Considered Options

* CSV with defined schema and JSON fields; import → draft; dry-run
* JSON-only import
* Direct Google Sheets connector

## Decision Outcome

Chosen option: "CSV with defined schema and JSON fields; import → draft; dry-run", because it is universal and safe.

### Consequences

* Good, because per-row error reporting, mapping, preview
* Bad, because jSON inside CSV is awkward to edit by hand

### Confirmation

[AC-13](../acceptance-criteria.md).

## More Information

FR-40 – FR-42, FR-44. Formats: [ADR-0032](0032-csv-schema.md). Import removes the character added against formula injection.

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)

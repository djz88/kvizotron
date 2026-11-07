---
status: accepted
date: 2026-11-07
---

# ADR-0045: One import file with a quiz row, question export in Stage B, and a failed image keeps its question

## Context and Problem Statement

[ADR-0032](0032-csv-schema.md) put quiz settings in a separate file, and its confirmation needs an export, planned for D2. An import may name many image addresses, each slow and each able to fail for a moment.

## Decision Drivers

* A person or an LLM writes one file more easily than two
* Export followed by import must give the same quiz
* A file should not fail over one temporary outage
* An upload is untrusted, and a large one must not fill the disk

## Considered Options

* A quiz row in the file, question export now, a failed address kept with a warning
* Two files as in ADR-0032, no export until D2, a failed address as a row error

## Decision Outcome

Chosen option: "A quiz row in the file, question export now, a failed address kept with a warning", because a file then round-trips and one bad address costs nothing.

* The first row with `row_type=quiz` holds name, description, languages and settings. It is ignored, with a warning, when adding to a draft or a bank.
* Each question type reads and writes its own columns through `csv_columns`, `from_csv` and `to_csv`. A setting's column works without touching the importer, as scopes come from the catalogue.
* `correct` holds option letters only.
* Export of questions moves to Stage B, as a CSV, or as a ZIP when an image is a local file. D2 keeps results, participants and statistics.
* An address that fails at confirmation keeps its question with no copy, with a warning. Publication in `copy` mode names it, as [ADR-0043](0043-external-images.md) does. This differs from the editor, which refuses in that mode. One confirmation counts as one save, sharing the 25 s budget.
* A file in a ZIP that cannot be used costs its row, as it will stay wrong.
* Limits are constants, not settings, so the module states `settings: []`: CSV 5 MB and 2000 rows; ZIP upload 100 MB, 500 entries, 200 MB unpacked. A ZIP is never unpacked to disk, and its entry names are only compared with cells. Each admin has at most one unconfirmed import, for 24 h, removed when a later import runs.
* Exported cells that a spreadsheet would run as a formula get `'` in front. Import removes one, so a text really starting with `'` survives.

### Consequences

* Good, because downloading, editing and importing back works today
* Bad, because a download holds answer keys, so it is admin only and audited
* Bad, because draw rows are not in the file, and the page says so

### Confirmation

[AC-49](../acceptance-criteria.md) to [AC-52](../acceptance-criteria.md).

## More Information

Refines [ADR-0032](0032-csv-schema.md) and [ADR-0043](0043-external-images.md). Column description for people and LLMs: `app/providers/csv_io/sample/csv-format.md`.

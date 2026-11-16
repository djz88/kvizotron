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

* **A `folder` column in a bank file (addendum 2026-11-11).** A bank file has a `folder` column with the folder of the question as a path with `/` (`EU/trade`, [ADR-0041](0041-draw-rows-and-flow-settings.md)). Import creates the missing folders, in the same transaction as the question, and finds an existing one regardless of case, so a bank can be filled from a file. A path with an empty segment, a name over 80 characters or a fifth level is an error on that row only. Into a draft or a new quiz the column is ignored with a warning, as `tags` is. Export writes the path, so a bank downloaded and imported again gives the same folders and tags ([AC-157](../acceptance-criteria.md)).

* **One level in `tags` (addendum 2026-11-12).** In a bank file `tags` may hold one of `easy`, `normal` and `hard`, which sets the difficulty a draw row can ask for ([ADR-0041](0041-draw-rows-and-flow-settings.md)). A question without one counts as `normal` when drawn, so import writes nothing for it. More than one of the three is an error on that row only, with the column `tags`, and the bank question form refuses it too ([AC-164](../acceptance-criteria.md)). The file guide says so.

* **Replacing the questions of a bank (addendum 2026-11-12).** The bank page has a second entry, "Replace questions", with the import target `bank_replace:<bank id>`, because a file has no stable key to update questions one by one and a bank that quizzes draw from cannot be deleted and made again. The check page shows how many questions will be deleted and which quizzes draw from the bank. Every row must be usable: an error row refuses the file, since a skipped row would delete its old question without a replacement. A confirmed replace saves the file's questions first and then deletes the questions that existed before, in one transaction, so a failed save changes nothing. Folders are kept, so draw rows keep working, and published revisions keep their copies ([AC-165](../acceptance-criteria.md)).

* **Folder placement (addendum 2026-11-12).** A file's folder paths are relative to the bank, but a file made elsewhere often adds a level of its own (`EU/trade` where the bank has `trade`), and draw rows name folders by id, so such an import used to fill new folders beside the ones the rows draw from. The check page of a bank import therefore shows the folder tree the questions will land in and lets the admin put everything under an existing folder, add a top folder, or rename or remove the top folders of the file. The choice travels in the check page address and the confirm form, not with the job: no contract or schema change, and the confirm validates it again. The paths are rewritten before the plan is judged, so errors and the replace refusal see the final paths. A replace also lists the draw rows that would come up short; it warns and does not block ([AC-166](../acceptance-criteria.md)).

### Consequences

* Good, because downloading, editing and importing back works today
* Bad, because a download holds answer keys, so it is admin only and audited
* Bad, because draw rows are not in the file, and the page says so

### Confirmation

[AC-49](../acceptance-criteria.md) to [AC-52](../acceptance-criteria.md).

## More Information

Refines [ADR-0032](0032-csv-schema.md) and [ADR-0043](0043-external-images.md). Column description for people and LLMs: `app/providers/csv_io/sample/csv-format.md`.

---
status: accepted
date: 2026-11-07
---

# ADR-0041: Draw rows set points; flow settings apply immediately and freeze on the attempt

## Context and Problem Statement

Milestone B3 brings question banks, random selection, navigation modes and revealing answers. Three things needed a decision: how drawn questions are worth points when participants get different ones, whether navigation and reveal are part of a revision, and how a participant reaches answers after a run closes, given that a result has no lasting address and answers are not stored.

## Decision Drivers

* Everyone in a run plays for the same maximum, because Stage C compares them on a scoreboard
* A published revision never changes; a bank edit does not reach it
* Few writes and no stored answers
* Simple settings that work like the existing ones

## Considered Options

* Points on the draw row, or points carried by each bank question
* Flow settings in the revision, or in the settings catalogue with a quiz override
* "After the run closes" in B3 with a lasting link, or moved to Stage C

## Decision Outcome

* **The draw row sets the points.** `max_score` is own points plus count × points per row, so it does not depend on the draw. The scoring strategy stays on the question.
* **Flow settings live in the settings catalogue**, global with a quiz override, effective for new attempts at once and creating no draft. An attempt freezes them at start in `settings_json`, next to the questions it got in `selection_json`. A conflict the form cannot see, from a later global change, falls back to `at_end` with a warning on the quiz.
* **Showing answers after the run closes moves to Stage C**, with identity and a lasting result page. In B3 the list exists only in the response to the submission, so nothing about answers is stored.

Publication copies each row's usable questions into the revision. A bank question whose pool differs from that copy counts as an unpublished change.

* **Bank folders (addendum 2026-11-11).** A bank holds a tree of folders, at most four levels deep, each an object of its own (`bank_folder`): created empty, renamed, and moved with its whole content. A question lies in one folder or in none; tags stay as a second, independent axis. A folder name has 1 to 80 characters, no `/`, and is unique among its siblings by `casefold()`. A folder cannot move into itself or its subfolders, nor so that its subtree passes four levels. A folder is deleted only when it holds no question and no subfolder, because a deleted question returns only from a backup; deleting a bank removes its folders. The rules are in `app/domain/bank_folders.py` ([AC-153](../acceptance-criteria.md)).
* **A folder moves between banks (addendum 2026-11-11).** One page moves a folder with everything in it: inside its bank (to the top or under another folder), to the top of another bank or under one of its folders, or out of its bank as a new bank named like the folder, whose top is then the folder's subfolders (its own questions are unfiled there). Depth and name rules hold at the destination, and a refusal changes nothing. A folder that a draw row of a draft, published or archived revision names by id, or contains such a folder, cannot leave its bank, because the row would then point at nothing; the message names the quizzes, as for deleting a bank. A whole-bank row only sees its pool change, which shows as an unpublished change ([AC-159](../acceptance-criteria.md)).
* **A draw row can name a folder (addendum 2026-11-11).** The row keeps `folder_id` (the folder, by id, so a rename or a move never breaks it) and `folder_path` for labels and the change overview. A folder includes its subfolders; a folder with a tag means a question must match both; neither means the whole bank, unfiled questions included, as before, and a row written earlier has neither key. A folder that is gone or is not the bank's gives an empty pool, and publication already refuses a row it cannot fill (AC-31). A rename, a move or a changed folder content does not touch a published revision, which keeps its copies (AC-32; [AC-154](../acceptance-criteria.md)).

* **Names edited on the spot (addendum 2026-11-11).** The name of a bank and of a folder is changed with a pencil next to it (AC-160), in a list and, for a folder, also from inside it; a refusal is shown beside the field. Bank and folder names keep one value for all languages. The bank page lists the languages its questions are complete in with their numbers and lets one choose the language of the listed question texts (AC-162). A rename touches only the name: draw rows refer to a folder and to a bank by id.

* **A difficulty on the draw row (addendum 2026-11-12).** A bank question's difficulty is one of the tags `easy`, `normal` and `hard` (compared like any tag, so case and spaces do not matter); a question with none counts as `normal` when the pool is built, so existing banks need no migration and the tags are never rewritten. A row keeps `difficulty` (`""`, `easy`, `normal` or `hard`); a row written earlier has no key and means a random mix, which neither filters nor weighs. A level, a folder and a tag must all match when set, and a question that carries two level tags (saved before the rule) matches both. The row label shows the level after the folder and the tag. A published revision keeps its copies ([AC-163](../acceptance-criteria.md)).

### Consequences

* Good, because maxima are equal and a scoreboard stays fair
* Good, because a settings change cannot alter an attempt in progress, and it needs no new revision
* Bad, because flow settings are not in the revision history, only in the audit log
* Bad, because a participant who leaves the result page cannot see the answers again until Stage C

### Confirmation

`tests/domain/test_draws.py`, `tests/domain/test_flow_settings.py`, `tests/integration/test_banks_and_flow.py`.
* **Runs keep these values (addendum 2026-11-18).** For a planned or open run the flow settings no longer apply to new attempts at once: a run keeps the values from planning or opening, and a change reaches it only when the admin answers so ([ADR-0069](0069-run-keeps-flow-settings.md)). Test runs and the preview still follow the quiz.

## More Information

FR-17, FR-18, FR-19, FR-23; [ADR-0035](0035-immediate-solutions-only-without-competition.md), [ADR-0038](0038-revision-switch-policy-and-settings.md).

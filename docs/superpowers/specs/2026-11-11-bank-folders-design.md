# Question bank folders: design

Tags: **[user]** the user decided, **[docs]** already in `docs/_architecture`, **[call]** my choice, open to correction.

## Why

A bank is a flat list of questions with flat tags. Authors want to see where a question belongs thematically (for example `EU → trade`, `EU → geopolitics`), to find questions by searching, and to see how much is in each branch. The trigger is a 25-question quiz about the EU that should become a bank from which a shorter quiz (15 questions, evenly from five topics) draws. Without a structure the bank is hard to read and a draw row can only pick by a single tag.

This is the first of two projects. The second, converting `kviz_eu_cr_25_otazek.json` to a bank plus a short quiz, comes after this one and will use the `folder` column defined here. **[user]** order: folders first.

## Goals

1. **Folders inside one bank [user]**: a tree, at most **4 levels** deep (`EU → economy → funds → regions` is the maximum). A question lies in exactly one folder or in none ("Unfiled"). Existing questions stay unfiled, nothing is lost.
2. **Folders are objects of their own [user]**: they can be created empty, renamed and moved with their whole content. They are not derived from a question's path.
3. **A folder is deleted only when empty [user]**: with the message "Move or delete the questions and subfolders first". Reason given: deleted questions come back only from a backup.
4. **A new bank page replaces the flat list [user]**: the tree with counts, a search box, the questions of the selected folder.
   - Each folder shows its number of questions **including subfolders** and its number of **direct subfolders**, for example "EU: 23 questions, 5 subtopics". Each subfolder shows its own count the same way. **[call]** the subfolder count is direct children only.
   - **Search [user: "searching in the bank"]** finds questions in the whole bank by question text, tags and folder name, and shows the folder path of each hit. **[call]** case-insensitive and diacritics-insensitive, because the texts are Czech and Ukrainian.
5. **Tags stay [user]** as a second, independent axis. A question has one folder and any tags.
6. **Moving questions [user]**: a "Folder" field in the question editor; in the question list several questions can be ticked and moved in one action to a chosen folder.
7. **Draw rows [user, call on the exact rule]**: a draw row in a quiz can name a folder, a tag, both, or neither. A folder includes its subfolders. Both given means a question must match both. Neither given keeps today's behaviour (the whole bank, unfiled questions included). Published revisions are unchanged: a revision keeps its copy of the questions, as ADR-0041 says.
8. **Import and export [user]**: a bank import and export has a `folder` column with a path such as `EU/trade`. Import **creates missing folders** by itself (within the depth limit), so a bank can be filled from a file with no clicking. Export writes the path back, so export followed by import gives the same bank.

## Non-goals

- Folders in a quiz draft, nested banks, sharing a question in several folders.
- Per-folder permissions: every admin can do in a folder what they can do in the bank today.
- Drag and drop (the user was asked and chose the field and bulk move only).
- Re-sorting or ordering folders by hand: **[call]** folders and questions are listed alphabetically by name, and by creation order for questions as today.
- The conversion of the EU JSON file (second project).

## Anti-goals

- A move, rename or import that silently changes a published revision or an attempt in progress (AC-32).
- A tree that becomes slow or unreadable on a phone: the page must work at 390 px.
- A folder name that breaks the CSV path (see constraints).
- Losing questions when a folder is touched.

## Constraints

- Project rules apply: a new model and migration make this a large change in `CLAUDE.md` terms. **[user]** Decisions are recorded by **updating existing ADRs**, not by a new one: a dated addendum (as ADR-0054 already does) in ADR-0041 for the bank folders and the draw-row rule, and one in ADR-0045 for the `folder` column of a bank file. Nothing is superseded and no ADR number is added. New acceptance criteria carry the AC id in their test docstrings, and `docs/_architecture/data-model.md`, `modules/api-ui.md` and the bank sections of the architecture docs are updated. `make quality` must pass.
- `bank_question.folder` is nullable. Deleting a bank must keep working as it does today.
- Folder names: not empty, at most 80 characters **[call]**, no `/`, unique among siblings compared case-insensitively. The path separator in CSV is `/`.
- Depth limit 4 holds for create, move (the moved subtree's height counts) and import. A folder cannot move into itself or into one of its own descendants.
- Texts are translated (cs, uk) and `make messages` is run. The user's `.mo` noise is not committed.
- No new setting. A folder name is one string, not per language **[call]**: the existing bank name is also one string.
- Audit entries for folder create, rename, move, delete and for the bulk move, in the same style as the existing `bank.*` actions, with no personal data.

## Calls found while checking the code **[call]**

- A draw row refers to a folder **by its id**, not by its path, so renaming or moving a folder never breaks a row. A row that points at a folder that is empty or gone simply cannot be filled, and publication already refuses such rows (AC-31). No extra rule.
- Deleting a bank (allowed today only when no quiz uses it, `banks.delete`) also deletes its folders, in the same transaction.
- The label of a draw row (`authoring.py` around line 383, `revision_diff.py` around line 107, both now "bank (tag)") must show the folder path as well, or the diff of two revisions would hide a changed folder.
- A bulk move and an import that creates folders are one transaction each: either everything is applied, or nothing.
- In the import, a folder path in a file for a quiz draft or a new quiz is ignored with a warning, as `tags` already is (`question_import.py`, `target.kind != "bank"`).

## What is left to the builder

Table and field names; URL names and whether the tree uses HTMX or full-page loads; how the tree is drawn (nested `details` or lists) and how the bulk move control looks; the exact migration; how the selector for the draw row offers folders (a path list is enough); how `revision_diff.py` and `authoring.py` treat the new draw-row key; where tests and ACs are placed, following `tests/CLAUDE.md`.

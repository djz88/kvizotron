# Where an import puts its folders — design

Date: 2026-11-12. Status: draft for approval.

## Why

The `folder` column of a file holds paths relative to the bank. A file made by hand or taken from another bank often adds a level of its own (`EU/geopolitika`, `EU/obchod`) while the bank keeps `geopolitika` and `obchod` at its top level. The import then creates `EU` with new subfolders beside the old ones. Draw rows name folders by id, so after a replace they point at folders that are now empty and the quiz editor shows "0 of 0", with no warning beforehand. This happened on the user's instance on 2026-11-12.

The admin should see on the check page where the questions will land, and change it there: rename a top folder, remove the top level (so `A`, `B`, `C` stay), add a top level, or put everything under an existing folder.

## What

1. **A structure block on the check page** for a bank target (import into a bank and replace). It shows the folder tree as it will be in the bank after the import, with the bank name (and the chosen parent folder, item 2) as the root. Each folder has the number of the file's questions in it and in its subfolders, and says "exists" or "new" (an existing folder is found the way the import finds it: by name with `casefold()`, level by level). Questions without a folder are counted on a line of their own. The tree holds the file's folders only; below it one line names the top-level folders of the bank that the file does not use ("Folders of the bank the file does not use: …"; for a replace: "… will be empty after the replace"), so `EU (new)` beside an unused `geopolitika` is plain to see. The block is not shown for a quiz target, where the folder column is not used. It is shown whenever the file has a question, also when a replace is refused, because the controls can fix some refusals (a path too deep).
2. **Controls under the tree**, a plain `GET` form on the check page (nothing is stored, so no CSRF and no new state):
   - "Put under": the top level of the bank or any existing folder of the bank (`bank_folders.choices`).
   - "Add a top folder": an optional name; every path of the file goes under a folder of this name, created under "Put under" when it does not exist. Questions without a folder in the file go there too (into the added folder, else into "Put under"; with neither they stay without a folder).
   - One line for each top-level folder of the file, in name order: a name field (rename) and a checkbox "remove this level". A removed level disappears; its subfolders and questions move one level up (questions that were directly in it land in the parent: the added top folder, the "Put under" folder or no folder).
   - Button "Apply the structure". The check page reloads with the values in its address and everything on it (tree, counts, errors, draw rows) is computed from them.
   Only the top level of the file is editable; deeper levels keep their names and order.
3. **The import uses exactly what the page showed.** The confirm form carries the same values as hidden fields. The server reads them again on confirm, validates them the same way and rewrites each planned question's folder before saving. A value that is no longer valid (a folder deleted meanwhile, a folder of another bank, a bad name) refuses the confirm with a message and nothing is imported. "Upload another file" starts without the values.
4. **Validation.** A name follows the folder rules (1 to 80 characters, no slash). A rewritten path deeper than four levels is an error on its rows, shown on the check page; for a replace that refuses the replace (the existing strict rule), for an import those rows are skipped as today. The rewrite runs before the plan is judged, so the refusal and the errors always reflect the chosen structure; the refusal text of a replace says the rows can be fixed in the file or, for folder errors, in the structure above. Two top folders renamed to the same name merge, as the import already merges paths that match.
5. **Draw rows after a replace.** For a replace, the check page lists every draw row that the quiz editor shows for a quiz drawing from this bank (`authoring.editable_draws`: the draft, else the latest published, else the archived revision; archived quizzes left out) that would have fewer questions than it asks for after the replace: quiz, folder path or "whole bank", difficulty, "available of wanted". Available counts what the editor will count after the replace: the file's questions whose rewritten path lies in the row's folder or below it, matching the row's tag and difficulty the way a draw does (no level tag means normal), and usable in the quiz's languages by the same test the draw uses (`banks._usable` on the question as it will be saved). A row whose folder would not exist after the replace counts 0. This is a warning: it does not block the replace. Without short rows nothing is shown.
6. **Domain, not view.** The rewrite of paths, the tree with "exists"/"new" and the draw-row check live in `app/domain/question_import.py` (or a small module beside it), pure functions over the plan and the bank, tested without pages. The view only reads the form values and renders.
7. **Audit unchanged** (`import.applied` keeps counts only). The format guide (`csv-format.md`) says the folder paths are relative to the bank and that the check page can rename, remove or add the top level.
8. **Docs.** AC-166, an addendum to ADR-0045, README range `AC-01…AC-166`, a line in `app/domain/CLAUDE.md`, Czech and Ukrainian translations.

## Not in scope

- Renaming or moving folders deeper than the top level of the file.
- Storing the structure choice with the import job (it travels in the address and the confirm form).
- Changing the folders that already exist in the bank, or deleting folders left empty by a replace (the bank page does that).
- Warnings about draw rows for a plain import (it only adds questions).

## Calls made here

- The choice travels in the address and the confirm form rather than in the job: no contract or migration change, and a reload shows the same page. The cost is that "Upload another file" forgets it.
- Only the top level is editable, which is what a foreign file adds; the user agreed.
- The draw-row list is a warning, not a refusal: an admin may replace first and fix the rows after.
- The tree shows the file's folders, plus one line with the bank's top folders the file leaves out (not the whole bank tree).
- Questions without a folder follow "Put under" and "Add a top folder" like the rest of the file.
- The draw-row check counts usable questions and takes the same rows as the editor, so it predicts exactly what the editor will show.

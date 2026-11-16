# Difficulty of bank questions — design

Date: 2026-11-12. Status: approved in conversation (the proposal was played back and the user started the workflow).

## Why

A bank holds questions of mixed difficulty, and a quiz built from it needs a way to ask for easy, normal or hard ones without adding one draw row per level. The user does not want to complicate the quiz settings: one dropdown on the draw row is enough for now.

## What

1. **Level = a reserved tag.** A bank question carries its difficulty in its existing `tags` list as one of `easy`, `normal`, `hard` (compared with `normal_tag`, so case and spaces do not matter). No new field, no migration.
2. **No level tag means `normal`.** The rule is applied when the pool is built (`banks.difficulty_of(tags)`), never written into the stored tags. It therefore covers CSV import, the bank question editor and banks that exist today.
3. **A draw row has a "Difficulty" dropdown:** `Random mix` (the default, stored as no key or `""`), `Easy`, `Normal`, `Hard`. The row stores `difficulty` (`""`, `easy`, `normal` or `hard`). A row written earlier has no key and means a random mix. A level filters together with the folder and the tag: a question must match all that are set. `Random mix` does not filter and does not weigh.
4. **One level per question.** A question with more than one of the three tags is refused: an import row is skipped with an error naming the column, the bank question form shows a message. Other tags are free as before.
5. **Labels.** The three tag values stay English in the data in every language. The UI shows translated labels (cs: Snadná, Normální, Těžká; uk: Легка, Звичайна, Складна; the mix: Náhodný mix / Випадковий мікс). The row label in the quiz editor, in the publication problems and in the change overview shows the level label after the folder and the tag.
6. **Documentation of the import.** `app/providers/csv_io/sample/csv-format.md` says that `tags` may hold one of `easy`, `normal`, `hard` and that a question without one is `normal`; the sample file shows it. The rule is also in the AC list and in the addenda of ADR-0041 (draw rows) and ADR-0045 (CSV).

## Not in scope

- A dropdown for the difficulty of a question in the bank editor (the tags field is enough).
- Weighted or proportional mixes, or "at most one question per topic".
- Detecting duplicate questions in a bank.
- Moving existing `Random mix` rows or changing published revisions: a published revision keeps its copies (AC-32).

## Decisions that are the builder's, now fixed

- The level is matched at the time the pool is built (publication and the usable-count check), so changing a question's tags changes only drafts, as it does for any tag.
- The tag datalist of the draw form lists the tags of the bank as before, including the three level tags if used; the dropdown is the intended way to choose a level.
- More than one level on a question is an error, not a "hardest wins" rule, because a silent choice would draw the question in a pool the author did not expect.

## Layers touched

`app/domain/banks.py` (levels, `difficulty_of`, filter in `_matching`, validation), `app/domain/authoring.py` (`save_draw`, row label), `app/domain/revision_diff.py` (label), `app/domain/question_import.py` (one level per row), `app/api/admin_forms.py` (`DrawForm.difficulty`, tags validation), `app/api/admin_banks.py` (pass through, initial value), draw form and quiz editor templates, the guide files of the csv provider, `docs/_architecture/` (AC, ADR-0041, ADR-0045, README range), translations.

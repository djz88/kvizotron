# Where an import puts its folders — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The check page of a bank import shows the folder tree the import will create, lets the admin rename or remove the file's top folders, add a top folder or put everything under an existing folder, and for a replace lists the draw rows that would come up short.

**Architecture:** A `Placement` (parsed from form values) rewrites each planned question's folder path inside `question_import.interpret`, before the plan is judged, so errors, refusals and `apply` all see the final paths. A new pure module `app/domain/import_structure.py` builds the tree with "exists"/"new" and the short draw rows from the plan. The view reads the values from the check page's `GET` form and from hidden fields of the confirm form; nothing is stored with the job.

**Tech Stack:** Django, Jinja2, pytest, Babel catalogues.

**Spec:** `docs/superpowers/specs/2026-11-12-import-folder-structure-design.md`

## Global Constraints

- No new route, no contract or model change, no migration; the structure choice travels in the check page address and the confirm form.
- CSRF on the confirm `POST` (exists); the structure form is `GET` and changes nothing. No inline scripts or styles.
- Only the top level of the file is editable; deeper levels keep their names.
- Folder names follow `bank_folders` rules: 1 to 80 characters, no slash; folders match by `casefold()` level by level; at most four levels (`bank_folders.MAX_DEPTH`).
- The draw-row warning never blocks; it counts what the quiz editor will count (`authoring.editable_draws`, usable in `quiz.supported_locales`, folder subtree, tag, difficulty with no level = normal), archived quizzes left out.
- Audit unchanged (counts only). New strings through `gettext`, cs and uk filled; docs in English; README AC range becomes `AC-01…AC-166`.

## Review Focus

- The user's incident: bank with top folders `geopolitika`, `obchod` and draw rows on them; replace with a file whose paths are `EU/geopolitika`, `EU/obchod` and "remove EU" chosen; after confirm the rows count the new questions and no `EU` folder exists.
- A hand-edited confirm `POST` with a folder id of another bank, a deleted folder or a name with a slash imports nothing and says why.
- A question directly in a removed top folder lands in the parent (added folder, "put under" folder, or no folder), never lost.
- A refused replace (error row) still shows the structure block, and a path made too deep by "Add a top folder" is a row error that refuses a replace.
- Two top folders renamed to the same name (any case) merge into one folder, in the tree and in the bank.

---

### Task 1: Placement in the import plan (domain)

**Files:**
- Modify: `app/domain/question_import.py`, `app/domain/bank_folders.py`, `app/domain/banks.py`
- Test: `tests/domain/test_question_import.py`

**Interfaces:**
- Produces in `bank_folders.py`: `clean_name(name: str) -> str` (public name of `_clean`; keep `_clean` callers working by renaming all of them).
- Produces in `banks.py`: `matches(row: Mapping[str, Any], tags: Sequence[str]) -> bool` (the tag and difficulty test `_matching` uses, extracted; `_matching` calls it); `is_usable(question_json: Mapping[str, Any], locales: Sequence[str]) -> bool` (public name of `_usable`); `built_question(type_id: str, config: JSON, *, scoring: str | None, sources: Sequence[str] | None, explanation: Mapping[str, str] | None, setting_values: Mapping[str, str] | None) -> dict[str, Any]` (the `question_json` a new bank question gets, without saving; `save_question` builds a new row's json through the same code).
- Produces in `question_import.py`:
  - `@dataclass(frozen=True) class Placement: under: BankFolder | None = None; added: str = ""; names: Mapping[str, str] = field(default_factory=dict); dropped: frozenset[str] = frozenset()` — `names` and `dropped` are keyed by `casefold()` of the file's top folder name.
  - `class PlacementInvalid(Exception)` (message for the page).
  - `top_folders(parsed: ParsedFile, mapping: Mapping[str, str]) -> list[str]`: distinct first segments of the `folder` cell (after mapping, stripped) of question rows, first spelling kept, sorted by `casefold()`.
  - `placement_of(bank: QuestionBank, values: Mapping[str, str], tops: Sequence[str]) -> Placement`: reads `under` (folder id or empty), `added`, `name_<i>` and `drop_<i>` (`"1"`) where `i` is the index in `tops`; empty or missing values mean no change; raises `PlacementInvalid` for an `under` that is not a folder of `bank` (also a malformed id) and for a non-empty name that `clean_name` refuses.
  - `place(path: str, placement: Placement, under_path: str) -> str`: pure; `under_path` is the path of `placement.under` or `""`. Result = `under_path / added / (renamed top, or nothing if dropped) / rest`, empty parts left out; `""` in gives the prefix only.
  - `interpret(..., placement: Placement | None = None)`: when the target is a bank and a placement is given, rewrite every planned question's `folder` with `place` right after the rows are read and before the replace refusal; a result deeper than `bank_folders.MAX_DEPTH` levels becomes `Issue(row, "folder", _("The folder %(path)s would be deeper than %(count)s levels."), True)` and the question leaves the plan. The replace refusal text becomes `_("Replacing needs every row to be usable. Fix the rows listed, in the file or in the folder structure, and check again; nothing was changed.")`.

- [ ] **Step 1: Write the failing tests** in `tests/domain/test_question_import.py` (reuse `GOOD`, `plan_of`, `errors`, `make_bank`, `ADMIN_ID`; give `plan_of` a `placement=None` keyword passed to `interpret`):
  - `test_top_folders_are_the_first_levels_of_the_file`: rows with folders `EU/a`, `eu/b`, `X`, `""` → `["EU", "X"]`
  - `test_place_renames_drops_and_adds_the_top_level` (parametrised over `place` only): `("EU/a", Placement(dropped={"eu"}), "") → "a"`; `("EU", Placement(dropped={"eu"}), "") → ""`; `("EU/a", Placement(names={"eu": "Evropa"}), "") → "Evropa/a"`; `("a", Placement(added="Nové"), "") → "Nové/a"`; `("", Placement(added="Nové"), "Staré") → "Staré/Nové"`; `("EU/a", Placement(added="Nové", dropped={"eu"}), "Staré") → "Staré/Nové/a"`
  - `test_placement_of_reads_the_form_and_refuses_bad_values`: bank with folder `Staré`; values `{"under": str(folder.pk), "added": " Nové ", "name_0": "Evropa", "drop_1": "1"}` with tops `["EU", "X"]` → `Placement(folder, "Nové", {"eu": "Evropa"}, frozenset({"x"}))`; `under` of another bank's folder, `under="nic"`, and `added="a/b"` each raise `PlacementInvalid`
  - `test_the_incident_lands_in_the_existing_folders`: bank with folder `geopolitika` holding one question and a draw row on it (`tests.domain.helpers.add_row` with `folder=`); replace plan of two `GOOD` rows with `folder` `EU/geopolitika` and placement `dropped={"eu"}`; `apply` → the folder pk is unchanged, holds 2 questions, no folder named `EU` exists, `banks.usable_count(row, ["cs", "en"]) == (2, 2)` — docstring starts `AC-166:`
  - `test_a_question_directly_in_a_dropped_folder_goes_to_the_parent`: folder `EU`, placement `dropped={"eu"}, under=folder Staré` → the question is in `Staré`
  - `test_a_path_made_too_deep_is_a_row_error_and_refuses_a_replace`: folder `a/b/c/d` with `added="X"` → an error issue in column `folder`, `plan.questions == []`; the same as a replace target sets `plan.refused`
  - `test_two_tops_renamed_alike_merge`: tops `A`, `B` renamed to `Spolu` and `spolu` → after `apply` one folder holds both questions
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_question_import.py -q -k "top_folders or place or incident or dropped or deep or renamed_alike"` — Expected: FAIL (no `Placement`)
- [ ] **Step 3: Implement** the interfaces above; `banks.matches` and `banks.built_question` must leave `tests/domain/test_banks.py` and `tests/domain/test_draws.py` green.
- [ ] **Step 4: Run** `uv run pytest tests/domain -q` — Expected: PASS
- [ ] **Step 5: Commit** `git add app/domain tests/domain docs/superpowers && git commit -m "feat(import): place the file's top folders where the admin chooses (domain)"`

---

### Task 2: Tree and short draw rows (domain)

**Files:**
- Create: `app/domain/import_structure.py`
- Test: `tests/domain/test_import_structure.py`

**Interfaces:**
- Consumes: `ImportPlan` with rewritten folders, `banks.matches`, `banks.is_usable`, `banks.built_question`, `bank_folders.choices`, `authoring.editable_draws`, `banks.level_label` (Task 1 and existing).
- Produces:
  - `@dataclass(frozen=True) class PlannedFolder: name: str; path: str; count: int; exists: bool; children: list[PlannedFolder]` — `count` is the questions in the folder and below.
  - `@dataclass(frozen=True) class Structure: folders: list[PlannedFolder]; without_folder: int; unused: list[str]` — `folders` start at the bank's top level, siblings by `casefold()`, merged by `casefold()` (first spelling shown); `exists` when the bank has a folder of that path (compare each level with `casefold()`); `unused` are the bank's top-level folder names that no planned path starts with.
  - `structure(plan: ImportPlan, bank: QuestionBank) -> Structure`
  - `@dataclass(frozen=True) class ShortRow: quiz: str; folder: str; tag: str; difficulty: str; available: int; wanted: int` — `folder` is the path or `""` for the whole bank, `difficulty` the label or `""`.
  - `short_rows(plan: ImportPlan, bank: QuestionBank) -> list[ShortRow]`: for every quiz with `archived_at is None` and every row of `authoring.editable_draws(quiz)` with `bank_id == str(bank.id)`: available = planned questions whose folder equals the row folder's path or lies below it (`casefold()`, a row without `folder_id` takes all; a `folder_id` that is not a folder of the bank gives 0), `banks.matches(row, question.tags)`, and `banks.is_usable(banks.built_question(...), quiz.supported_locales)`; listed when `available < row["count"]`; ordered by quiz slug then row position.

- [ ] **Step 1: Write the failing tests** in `tests/domain/test_import_structure.py` (build plans with `question_import.interpret` on a `ParsedFile` like `tests/domain/test_question_import.py` does, or import its `plan_of`):
  - `test_the_tree_marks_existing_and_new_folders_and_counts_below`: bank with `Geopolitika`; file folders `geopolitika`, `ekonomika/fondy`, `ekonomika`, `""` → tree `geopolitika` exists count 1, `ekonomika` new count 2 with child `fondy` new count 1; `without_folder == 1`
  - `test_the_tree_names_bank_folders_the_file_leaves_out`: bank top folders `geopolitika`, `obchod`; file `EU/geopolitika` → `unused == ["geopolitika", "obchod"]`
  - `test_a_row_on_a_folder_the_file_leaves_empty_is_short`: quiz slug `evropa` with a row on folder `obchod` count 3; file into `EU/obchod` → `[ShortRow("evropa", "obchod", "", "", 0, 3)]` — docstring starts `AC-166:`
  - `test_a_row_that_gets_enough_is_not_listed_and_subfolders_count`: row on `ekonomika` count 2; file `ekonomika`, `ekonomika/fondy` → `[]`
  - `test_short_rows_follow_tag_difficulty_and_languages`: quiz in `cs,en`; row with `difficulty="hard"` count 1 and file with one `easy` question → listed; row without difficulty and a file question complete only in `cs` → listed with `available == 0`
  - `test_archived_quizzes_are_left_out_and_a_published_quiz_counts`: an archived quiz with a short row → not listed; a published quiz without draft with a short row → listed
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_import_structure.py -q` — Expected: FAIL (no module)
- [ ] **Step 3: Implement** `app/domain/import_structure.py` (module docstring: what the check page shows before a bank import; reads, never writes).
- [ ] **Step 4: Run** `uv run pytest tests/domain tests/test_layers.py -q` — Expected: PASS
- [ ] **Step 5: Commit** `git add app/domain tests/domain && git commit -m "feat(import): the folder tree and short draw rows of a bank import (domain)"`

---

### Task 3: Check page and confirm

**Files:**
- Modify: `app/api/admin_import.py`, `app/api/jinja2/admin/import_check.html`, catalogues of `app/api` and `app/domain`
- Test: `tests/api/test_import.py`

**Interfaces:**
- Consumes: `question_import.top_folders`, `placement_of`, `PlacementInvalid`, `interpret(..., placement=)`, `import_structure.structure`, `short_rows` (Tasks 1–2).
- Produces: `_placement(job, parsed, target, values) -> tuple[Placement | None, str | None]` in the view (placement, or the error message); `_plan` takes the placement. Check context adds `structure` (or None), `tops` (list of `{"index", "name", "value", "dropped"}`), `under_choices` (`bank_folders.choices`), `placement_values` (the raw values to repeat as hidden fields), `placement_error`, `short_rows`. The check page reads values from `request.GET`; confirm reads the same names from `request.POST`; an invalid placement at confirm sets `plan.refused = _("The folder structure is no longer valid: %(reason)s Nothing was imported.")` and imports nothing.

- [ ] **Step 1: Write the failing tests** in `tests/api/test_import.py` (a `FOLDER_HEAD = QUIZ_HEAD + ",folder"` and rows like `f"{GOOD},EU/geopolitika"`; folders via `bank_folders.ensure_path`):
  - `test_the_check_page_of_a_bank_import_shows_the_folder_tree`: upload into `bank:<id>` with folders `EU/geopolitika`; check page contains `EU`, `geopolitika`, the "new" label and "Apply the structure"; a `new_quiz` check page does not contain "Apply the structure"
  - `test_applying_the_structure_and_confirming_uses_it` (docstring `AC-166:`): bank with folder `geopolitika` and a row on it; replace upload with `EU/geopolitika`; `GET check?drop_0=1` shows `geopolitika` as existing and the confirm form holds `name="drop_0"`; `POST confirm` with `{"drop_0": "1"}` → questions in the old folder, no `EU` folder
  - `test_a_tampered_structure_imports_nothing`: `POST confirm` with `{"under": str(folder_of_another_bank.pk)}` → report contains "no longer valid", bank unchanged
  - `test_a_bad_name_on_the_check_page_hides_the_confirm`: `GET check?name_0=a/b` → the name rule message and no `/confirm` form
  - `test_the_replace_check_lists_short_draw_rows`: quiz `evropa` with a row on `obchod` count 3; replace with `EU/obchod` → page contains `evropa`, `obchod` and `0 of 3`; with `?drop_0=1` the row is not listed
  - `test_a_refused_replace_still_shows_the_structure`: replace with `GOOD` and `BAD` rows with folders → refusal text and "Apply the structure" both present
- [ ] **Step 2: Run** `uv run pytest tests/api/test_import.py -q -k "structure or tree or short_draw or tampered or bad_name"` — Expected: FAIL
- [ ] **Step 3: Implement** the view and template: the structure block (heading "Where the questions go", nested `<ul>` with name, count and "exists"/"new", line "Without a folder: %(count)s", line "Folders of the bank the file does not use: %(names)s" or for a replace "… they will be empty after the replace"), the `GET` form (`under` select with "Top level of the bank", `added` text, per top a name field and checkbox "Remove this level", button "Apply the structure"), the short rows list for a replace ("Draw rows that will get fewer questions than they ask for" with "%(quiz)s · %(folder)s · %(available)s of %(wanted)s", "whole bank" when no folder, difficulty label when set), and hidden inputs of `placement_values` in the confirm form. The block shows whenever the target is a bank and the plan has questions, outside the `refused` branch. Keep labels tied to inputs (`<label for>`).
- [ ] **Step 4: Run** `uv run pytest tests/api tests/test_wiring.py -q` — Expected: PASS
- [ ] **Step 5: Translations**: `make messages`; fill cs and uk for every new string of the api and domain catalogues (Babel `read_po` / `write_po(width=0, omit_header=True, ignore_obsolete=True)`); `uv run pytest tests/test_translations.py -q` — Expected: PASS
- [ ] **Step 6: Commit** `git add app tests && git commit -m "feat(import): choose where a bank import puts its folders"`; stage only `.po` and `.mo` of the api and domain catalogues.

---

### Task 4: Documentation and checks

**Files:**
- Modify: `docs/_architecture/acceptance-criteria.md`, `docs/_architecture/README.md`, `docs/_architecture/adr/0045-csv-one-file-and-failed-images.md`, `app/domain/CLAUDE.md`, `app/providers/csv_io/sample/csv-format.md`

- [ ] **Step 1: AC-166** after AC-165: "The check page of a bank import shows and changes where the folders go" — tree with counts and exists/new, bank folders the file leaves out, put under an existing folder, add a top folder, rename or remove a top folder of the file, the confirm uses exactly the shown choice and refuses an invalid one, too deep is a row error, a replace lists draw rows that would get fewer questions (warning only); related FR-41, ADR-0045, ADR-0041; stage D. README range to AC-166. ADR-0045 addendum "Folder placement (addendum 2026-11-12)". `app/domain/CLAUDE.md`: one line for `import_structure.py` and the `Placement` in `question_import.py`. `csv-format.md`: the `folder` row says paths are relative to the bank and the check page can rename, remove or add the top level.
- [ ] **Step 2: Run** `uv run pytest tests/test_docs.py -q` — Expected: PASS
- [ ] **Step 3: Run** `make quality` — Expected: exit 0
- [ ] **Step 4: Browser check** on a throwaway instance (not the user's stacks): the incident (bank with flat folders and rows, replace with `EU/…`, remove `EU`, confirm, editor shows full rows); the check page at 1280 px light and 390 px dark; the structure form by keyboard. Report what was not seen in a browser.
- [ ] **Step 5: Commit** `git add docs app/domain/CLAUDE.md app/providers/csv_io/sample && git commit -m "docs: choosing where a bank import puts its folders (AC-166, ADR-0045)"`

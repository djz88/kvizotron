# Question Bank Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A question bank gets a tree of folders (at most 4 levels) with counts, search, a folder per question, bulk move, folder-aware draw rows and a `folder` column in bank import and export.

**Architecture:** A new model `BankFolder` (bank, nullable parent, name) and a nullable `BankQuestion.folder`. All rules live in a new domain module `app/domain/bank_folders.py`; `banks.py`, `authoring.py`, `question_import.py` and `question_export.py` call it. The bank page in `app/api/admin_banks.py` and `jinja2/admin/bank.html` is rebuilt as a folder view. A draw row refers to a folder by id and keeps its path for labels; the published revision still keeps copies (AC-32).

**Tech Stack:** Django, Jinja2, HTMX (optional), pytest (`uv run pytest`), `make quality`, `make messages`.

**Spec:** `docs/superpowers/specs/2026-11-11-bank-folders-design.md`

## Global Constraints

- At most **4 levels** of folders; a folder name is 1 to **80** characters, has no `/`, is unique among siblings compared with `casefold()`. [spec]
- A folder is deleted **only when empty** (no questions, no subfolders): message "Move or delete the questions and subfolders first". [spec]
- A question lies in exactly one folder or in none ("Unfiled"). Existing questions stay unfiled. [spec]
- Tags stay as a second, independent axis. [spec]
- Folder counts: questions **including subfolders**, and the number of **direct** subfolders; each subfolder shows its own count the same way. [spec]
- Search: case-insensitive, diacritics-insensitive; matches question text (any language), tags and folder path. [spec]
- A draw row may name a folder, a tag, both (both must match) or neither (whole bank, unfiled included); a folder includes its subfolders; it refers to a folder by id. [spec]
- CSV `folder` column: a path with `/`; import creates missing folders; export writes the path; round trip gives the same bank. In a quiz draft or new quiz the column is ignored with a warning. [spec]
- Decisions are recorded as **dated addenda to ADR-0041 and ADR-0045**, no new ADR. [spec]
- A bulk move and an import row that creates folders are one transaction each. Audit entries without personal data. No new setting. `.mo` noise of unrelated files is never committed. [spec, `CLAUDE.md`]
- Every behaviour change has a test; a new AC has a test with its id in the docstring (`AC-153: …`), the AC list is in `docs/_architecture/acceptance-criteria.md` (last id today: AC-152). Texts are translated into cs and uk with `make messages`.

## Review Focus

- Moving a folder into itself or into its own descendant, or so that its subtree becomes deeper than 4: refused, nothing changes.
- A CSV `folder` with an empty segment (`EU//trade`, leading or trailing `/`), a segment over 80 characters, a fifth level, or the same name in another case (`eu/Trade` when `EU/trade` exists): row error or reuse of the existing folder, never a crash, never a duplicate.
- A search with Czech diacritics (`ekonomika` finds `Ekonomika`, `cesta` finds `čeština`), Ukrainian `й` not equal to `и`, an empty query, and HTML in the query or in a folder name shown escaped on the page.
- A draw row whose folder belongs to another bank is refused; a published revision does not change when a folder is renamed or moved or a question is moved (AC-32).
- A bulk move that lists a question id from another bank, or a folder of another bank: nothing is moved and the admin sees an error.
- Deleting a bank that has folders removes them; a bank used by a quiz is still refused.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/domain/models.py`, `app/domain/migrations/0021_bank_folders.py` | `BankFolder`, `BankQuestion.folder` |
| `app/domain/bank_folders.py` (new) | folder rules, tree with counts, search, bulk move, `ensure_path` |
| `app/domain/banks.py` | `save_question(folder=…)`, `_matching` by folder, `delete` removes folders |
| `app/domain/authoring.py`, `app/domain/revision_diff.py` | draw row `folder_id`, `folder_path`, labels |
| `app/api/admin_forms.py`, `app/api/admin_banks.py`, `app/api/urls.py`, `jinja2/admin/bank.html`, `bank_question.html` (the existing question edit template, find it), `quiz_edit.html`, draw form template | UI |
| `app/domain/question_import.py`, `app/domain/question_export.py` | `folder` column |
| `docs/_architecture/adr/0041-…`, `0045-…`, `data-model.md`, `modules/api-ui.md`, `acceptance-criteria.md`, `app/domain/CLAUDE.md` | docs |
| `tests/domain/test_bank_folders.py` (new), `tests/api/test_admin_banks.py`, `tests/api/test_admin_draw.py`, `tests/domain/test_banks.py`, `tests/domain/test_draws.py`, `tests/domain/test_question_import.py` | tests |

---

### Task 1: Folder model and rules

**Files:**
- Modify: `app/domain/models.py` (after `BankQuestion`), `app/domain/banks.py` (`delete`)
- Create: `app/domain/migrations/0021_bank_folders.py`, `app/domain/bank_folders.py`
- Test: `tests/domain/test_bank_folders.py`
- Docs: `docs/_architecture/data-model.md` (rows for `bank_folder` and the new `bank_question.folder`)

**Interfaces:**
- Produces, model: `BankFolder(id: UUID uuid7, bank FK QuestionBank PROTECT related_name="folders", parent FK "self" null PROTECT related_name="children", name CharField(80), created_at)`, `db_table="bank_folder"`; `BankQuestion.folder = FK(BankFolder, null=True, blank=True, PROTECT, related_name="questions")`.
- Produces, `app/domain/bank_folders.py`:
  - constants `MAX_DEPTH = 4`, `MAX_NAME = 80`
  - exceptions `FolderNameInvalid`, `FolderNameTaken`, `FolderTooDeep`, `FolderCycle`, `FolderNotEmpty`, `WrongBank` (all subclass a base `FolderError(Exception)`)
  - `create(bank: QuestionBank, parent: BankFolder | None, name: str, *, admin_id: str | None) -> BankFolder`
  - `rename(folder: BankFolder, name: str, *, admin_id: str | None) -> None`
  - `move(folder: BankFolder, parent: BankFolder | None, *, admin_id: str | None) -> None`
  - `delete(folder: BankFolder, *, admin_id: str | None) -> None`
  - `path_of(folder: BankFolder | None) -> str` (`"EU/trade"`, `""` for None)
  - `subtree_ids(folder: BankFolder) -> set[UUID]` (the folder and all descendants)
  - `ensure_path(bank: QuestionBank, path: str, *, admin_id: str | None) -> BankFolder` (creates missing levels, reuses by `casefold()`)
  - `choices(bank: QuestionBank) -> list[tuple[str, str]]` (`(id, path)` sorted by path; used by forms)

- [ ] **Step 1: Write failing tests** in `tests/domain/test_bank_folders.py` (use `tests/domain/helpers.py` to build banks and questions):
  - `test_create_nested_up_to_four_levels_and_refuse_the_fifth` → `FolderTooDeep`
  - `test_name_rules`: empty, 81 characters, containing `/` → `FolderNameInvalid`; `"Trade"` then `"trade"` under the same parent → `FolderNameTaken`; the same name under another parent is fine
  - `test_move_into_own_descendant_is_refused` → `FolderCycle`; `test_move_checks_depth_of_the_whole_subtree` (a 3-level subtree cannot go under a level-2 folder) → `FolderTooDeep`; a failed move leaves `parent_id` unchanged
  - `test_delete_only_when_empty`: with a question → `FolderNotEmpty`; with a subfolder → `FolderNotEmpty`; empty → gone
  - `test_ensure_path_creates_missing_levels_and_reuses_by_casefold`: `ensure_path(bank, "EU/trade")` twice, then `"eu/Trade"` returns the same folder; `"EU//x"`, `"/EU"`, `"EU/"` → `FolderNameInvalid`
  - `test_deleting_a_bank_removes_its_folders` (via `banks.delete`) and `test_bank_in_use_is_still_refused`
  - `test_audit_entries_carry_no_personal_data`: actions `bank.folder_created`, `bank.folder_renamed`, `bank.folder_moved`, `bank.folder_deleted` exist with `details == {}`
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_bank_folders.py -q`. Expected: FAIL (module not found).
- [ ] **Step 3: Add the model and migration `0021_bank_folders`** (depends on `("domain", "0020_participant_email_key")`; run `uv run python manage.py makemigrations domain -n bank_folders` and check the result has no unrelated changes).
- [ ] **Step 4: Implement `bank_folders.py`** with the signatures above. Each write function runs in `transaction.atomic()`, checks that parent and folder belong to the same bank (`WrongBank`), and records the audit action like `banks._audit` does (entity `question_bank`, `details={}`). Depth of a move = depth of the new parent + height of the moved subtree.
- [ ] **Step 5: Change `banks.delete`** to delete the bank's folders (children first) before the bank, in the same transaction.
- [ ] **Step 6: Run** the new tests and `uv run pytest tests/domain/test_banks.py -q`. Expected: PASS.
- [ ] **Step 7: Update `data-model.md`** (two rows), then commit: `git add app/domain tests/domain docs/_architecture/data-model.md && git commit -m "feat(banks): folders in a question bank, rules and model"`

---

### Task 2: Tree, counts, search, bulk move

**Files:**
- Modify: `app/domain/bank_folders.py`, `app/domain/banks.py` (`save_question` gets `folder: BankFolder | None = None`)
- Test: `tests/domain/test_bank_folders.py`

**Interfaces:**
- Consumes: Task 1.
- Produces, in `bank_folders.py`:
  - `@dataclass(frozen=True) class FolderNode: folder: BankFolder; total: int; subfolders: int; children: list[FolderNode]` (`total` = questions in the folder and all below; `subfolders` = direct children count)
  - `tree(bank: QuestionBank) -> list[FolderNode]` (roots, alphabetical by `casefold()` name), built from two queries (folders, a count of questions per folder), not one per folder
  - `unfiled_count(bank: QuestionBank) -> int`
  - `search(bank: QuestionBank, text: str) -> list[BankQuestion]`; empty or blank text returns `[]`
  - `move_questions(bank: QuestionBank, question_ids: Sequence[Any], folder: BankFolder | None, *, admin_id: str | None) -> int` (one transaction; raises `WrongBank` if any id is not in the bank or the folder is of another bank; audit `bank.questions_moved`)
- `banks.save_question(..., folder=…)` sets `row.folder`; a folder of another bank raises `bank_folders.WrongBank`.
- Search text of a question: its prompt in every language of `question_import.languages()` obtained like `app/api/rendering.question_label` does (type plugin `public_payload(definition, locale)["prompt"]`), plus tags, plus `path_of(folder)`. Folding: `casefold()`, then removing combining marks **only from Latin letters** (so `й` stays distinct from `и`); the text plugin's diacritics option may already have such a helper, reuse it if so.

- [ ] **Step 1: Write failing tests:**
  - `test_tree_counts_include_subfolders`: EU(2 own) → trade(3), geo(1) gives EU `total == 6`, `subfolders == 2`, trade `total == 3`, `subfolders == 0`
  - `test_tree_uses_a_fixed_number_of_queries` (`django_assert_num_queries` with a bank of 10 folders)
  - `test_unfiled_count`
  - `test_search_ignores_case_and_diacritics` (Czech text `Čeština` found by `cestina`), `test_search_does_not_equate_ukrainian_i_and_y` (`й` vs `и`), `test_search_finds_by_tag_and_folder_path`, `test_blank_search_returns_nothing`
  - `test_move_questions_moves_all_or_nothing`: one id from another bank → `WrongBank`, none moved; folder of another bank → `WrongBank`; `folder=None` unfiles
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** `FolderNode`, `tree`, `unfiled_count`, `search`, `move_questions` and the `save_question` parameter.
- [ ] **Step 4: Run** `uv run pytest tests/domain/test_bank_folders.py tests/domain/test_banks.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(banks): folder tree with counts, search and bulk move`

---

### Task 3: Draw rows by folder

**Files:**
- Modify: `app/domain/banks.py` (`_matching`), `app/domain/authoring.py` (`save_draw`, `_rows_of`, `_row_label`), `app/domain/revision_diff.py` (`_draw_text`, `_draw_changes`), `app/api/admin_forms.py` (`DrawForm`), `app/api/admin_banks.py` (`_draw_form`, `_save_draw`, `_draw_page`), draw form template and `quiz_edit.html` (find them with `grep -rn "bank-tags" app/api/jinja2`)
- Test: `tests/domain/test_draws.py`, `tests/api/test_admin_draw.py`, `tests/domain/test_bank_folders.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: a draw row in `snapshot_json["draws"]` gains `folder_id: str` (`""` when none) and `folder_path: str`. `authoring.save_draw(quiz, draw_id, *, bank_id, tag, folder_id: str = "", count, points, position) -> str` raises `bank_folders.WrongBank` when the folder is not in the bank. `DrawForm` gets a `folder` `ChoiceField(required=False)` whose choices are all folders of all banks as `(folder id, "<bank name> / <path>")` with the empty choice "Whole bank"; the view rejects a folder that is not of the chosen bank with a form error.
- `banks._matching(row)` keeps today's tag rule and additionally restricts to `subtree_ids(folder)` when `row.get("folder_id")` is set; rows written earlier have no key and behave as before.
- Label: `_row_label` and `_draw_text` show `bank (folder path · tag)` parts that are present, so a changed folder shows in the revision overview.

- [ ] **Step 1: Write failing tests:**
  - `test_pool_of_a_folder_includes_subfolders`
  - `test_folder_and_tag_must_both_match`
  - `test_row_without_folder_key_still_draws_the_whole_bank` (old snapshot shape)
  - `test_unfiled_questions_are_in_a_row_with_no_folder_only`
  - `test_a_folder_of_another_bank_is_refused` (service raises `WrongBank`; the form shows an error and saves nothing)
  - `test_published_revision_does_not_change_when_a_folder_is_renamed_moved_or_a_question_is_moved` (AC-32: compare `snapshot_json` of the published revision before and after)
  - `test_revision_overview_shows_a_changed_folder`
  - `test_quiz_edit_shows_the_folder_path_on_the_row`
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces; `_rows_of` passes `folder_path` through to the template; the count `usable`/`total` keeps using `usable_count`.
- [ ] **Step 4: Run** `uv run pytest tests/domain tests/api/test_admin_draw.py -q`. Expected: PASS.
- [ ] **Step 5: Docs:** add a dated addendum (2026-11-11) to `docs/_architecture/adr/0041-draw-rows-and-flow-settings.md`: bank folders (tree, 4 levels, one folder per question, deletion only when empty), the draw-row rule (folder by id, subtree, with tag both, neither = whole bank), and that published revisions keep their copies. Add AC-153 (tree, depth, empty-delete), AC-154 (draw row by folder) to `acceptance-criteria.md`, with the AC ids in the docstrings of the tests above. Update `app/domain/CLAUDE.md` (`bank_folders.py` line) and `docs/_architecture/modules/api-ui.md` only in Task 6.
- [ ] **Step 6: Commit** `feat(banks): a draw row can draw from a folder`

---

### Task 4: Bank page as a folder view

**Files:**
- Modify: `app/api/admin_banks.py` (`_bank_page`, `bank_page`, new views), `app/api/urls.py`, `app/api/jinja2/admin/bank.html`, `app/plugins/theme_default/assets/theme.css` if styles are needed
- Test: `tests/api/test_admin_banks.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces URL names (all POST except the page): `admin_bank` (existing, `GET ?folder=<id>|none&q=<text>`), `admin_bank_folder_create` (`banks/<uuid:bank_id>/folders/new`, fields `parent`, `name`), `admin_bank_folder_rename` (`banks/<uuid:bank_id>/folders/<uuid:folder_id>/rename`, field `name`), `admin_bank_folder_move` (`…/move`, field `parent`), `admin_bank_folder_delete` (`…/delete`), `admin_bank_questions_move` (`banks/<uuid:bank_id>/questions/move`, fields `question` (repeated) and `folder`, empty = unfiled).
- The page (explorer style, my call): no `folder` param shows the root folders and the unfiled questions; `?folder=<id>` shows a breadcrumb path, that folder's subfolders (each with "N questions, M subtopics") and its own questions; `?folder=none` lists unfiled questions; `?q=` shows search results for the whole bank, each with its folder path as a link. Every folder row has an actions menu (rename, move, delete) as the question rows already have. A refused folder action re-renders the page with the error message of the exception in the existing `notice` block and status 400. Each question row has a checkbox and the list has one "Move selected to…" control with a folder select (`bank_folders.choices`) plus "Unfiled". "Add question" in a folder passes `?folder=<id>` on to the question editor (used in Task 5).

- [ ] **Step 1: Write failing tests** with the existing `FormClient`/`client` fixtures:
  - `test_bank_page_shows_tree_counts`: the page text contains "EU" with its total and subtopic count (cs wording from the locale file), and each subfolder its own count
  - `test_folder_page_lists_only_its_own_questions_and_subfolders`
  - `test_search_page_shows_hits_with_path_and_escapes_the_query` (`<script>` in `q` and in a folder name appear escaped)
  - `test_create_rename_move_delete_folder_through_the_views`; `test_delete_of_a_non_empty_folder_shows_the_message` (status 400, folder still there); `test_move_into_own_child_shows_an_error`
  - `test_bulk_move_moves_selected_questions` and `test_bulk_move_with_a_foreign_question_changes_nothing`
  - `test_every_view_needs_an_admin` (anonymous gets the login redirect, like the other bank views)
- [ ] **Step 2: Run** `uv run pytest tests/api/test_admin_banks.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the views (thin: they call `bank_folders` and render), routes and template. Keep the page usable at 390 px: indentation by nesting is limited by the breadcrumb model (only one level is listed at a time), so nothing nests deeper than one list.
- [ ] **Step 4: Run** the tests and `uv run pytest tests/test_wiring.py -q` (CSS classes must be used). Expected: PASS.
- [ ] **Step 5: Commit** `feat(banks): folder view of a bank with counts and search`

---

### Task 5: Folder of a question and the CSV column

**Files:**
- Modify: `app/api/admin_forms.py` (`BankQuestionForm`), `app/api/admin_banks.py` (`_question_page`, `_save_question`, `bank_question_new`, `bank_question_edit`), the bank question edit template, `app/domain/question_import.py`, `app/domain/question_export.py`
- Test: `tests/api/test_admin_banks.py`, `tests/domain/test_question_import.py`, `tests/api/test_import.py`

**Interfaces:**
- Consumes: Tasks 1 to 4.
- `BankQuestionForm` gets `folder = ChoiceField(required=False)` with choices `[("", "Unfiled"), *bank_folders.choices(bank)]`, passed as a keyword `folders` to `__init__`; `_save_question` passes the chosen `BankFolder` (or `None`) to `banks.save_question`; a new question opened with `?folder=<id>` has it preselected.
- Import: `PLAIN_COLUMNS` gains `"folder"`; `PlannedQuestion` gains `folder: str = ""`; in `_unused` a `folder` with values for a target that is not a bank is added to the ignored columns exactly like `tags` (warning); `_save_to_bank` calls `bank_folders.ensure_path` inside the row's existing transaction and turns a `FolderError` into an `Issue(question.row, "folder", message, True)` (row skipped, the rest imported).
- Export: `rows_for_bank` sets `row["folder"] = path_of(stored.folder)`; the exported header contains `folder` for a bank file.

- [ ] **Step 1: Write failing tests:**
  - editor: `test_question_can_be_saved_into_a_folder`, `test_new_question_from_a_folder_preselects_it`, `test_a_folder_of_another_bank_is_refused_in_the_editor`
  - import: `test_import_creates_missing_folders_from_the_folder_column` (`EU/trade` creates two folders and the question lies in `trade`), `test_import_reuses_a_folder_by_casefold` (`eu/Trade`), `test_import_row_with_a_bad_folder_is_skipped_with_an_error_and_the_rest_imported` (`EU//x`, a 81-character segment, a fifth level), `test_folder_column_is_ignored_with_a_warning_for_a_draft_and_for_a_new_quiz`
  - round trip: `test_bank_export_then_import_gives_the_same_folders_and_tags` (AC-155)
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces.
- [ ] **Step 4: Run** `uv run pytest tests/api tests/domain -q`. Expected: PASS.
- [ ] **Step 5: Docs:** dated addendum (2026-11-11) to `docs/_architecture/adr/0045-csv-one-file-and-failed-images.md` for the `folder` column (path with `/`, missing folders created, ignored with a warning outside a bank, export writes it); update the column table in `app/providers/csv_io/sample/csv-format.md` and the sample if it has a bank example; add AC-155 (bank file with folders) to `acceptance-criteria.md`.
- [ ] **Step 6: Commit** `feat(banks): folder of a question, folder column in a bank file`

---

### Task 6: Translations, documentation, quality and browser check

**Files:**
- Modify: `app/api/locale/{cs,uk}/LC_MESSAGES/django.po`, `app/domain/locale/{cs,uk}/…` (and any other catalogue `make messages` changes for the new texts), `docs/_architecture/modules/api-ui.md` (banks row and the page), `docs/_architecture/README.md` only if it lists the bank page, `acceptance-criteria.md` (AC-156: bank page with counts and search; AC-157: bulk move)
- Test: `tests/test_docs.py` and the full suite

- [ ] **Step 1: Run** `make messages`, fill every new `msgstr` in cs and uk, and run it again. Stage only the catalogues whose `.po` you changed and their `.mo`; the 38 unrelated `.mo` files stay unstaged.
- [ ] **Step 2: Update** `api-ui.md` and the AC list so every new AC has a test docstring naming it; remove from `AC_NOT_NAMED_BY_A_TEST` only if the list names them.
- [ ] **Step 3: Run** `make quality`. Expected: lint, tests, gitleaks and the tech-debt check pass.
- [ ] **Step 4: Browser check** with the `kvizotron-browser-walkthrough` skill on a throwaway instance (do not touch the `kvizotron-browser` stack): 1280 px light `cs` and 390 px dark `uk`; create a three-level tree, move questions in bulk, search with and without diacritics, try deleting a non-empty folder, add a draw row by folder and publish. Open the screenshots; `errs` must be empty.
- [ ] **Step 5: Commit** `docs(banks): translations, acceptance criteria and bank page description`

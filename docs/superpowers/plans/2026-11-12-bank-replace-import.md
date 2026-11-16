# Replace the questions of a bank by an import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An import can replace all questions of an existing bank, keeping the bank, its folders and the draw rows that point to them.

**Architecture:** A new import target kind `bank_replace` maps to `Target("bank", None, bank, replace=True)`. `question_import.apply` saves the new questions, then deletes the ids that existed before, in one transaction; any save problem raises `ReplaceRefused` and rolls back. The check page shows the effect and the quizzes using the bank.

**Tech Stack:** Django, Jinja2, pytest, Babel catalogues.

**Spec:** `docs/superpowers/specs/2026-11-12-bank-replace-import-design.md`

## Global Constraints

- CSRF on every admin POST and no inline scripts or styles (the confirm form exists already; no new route).
- Audit entries carry counts only (`replaced`, `removed`), no texts or names.
- A published revision keeps its copies; folders are never deleted by a replace; the bank id does not change.
- Nothing changes before the admin confirms; a refused or failed replace changes nothing.
- New strings go through `gettext`, cs and uk filled; docs in English; README AC range becomes `AC-01…AC-165`.

## Review Focus

- A file where every row fails deletes nothing, and a file with one error row is refused with the bank untouched.
- A save problem inside `apply` (folder error) rolls back the new questions too, and the old ones stay.
- Only questions that existed before the import are deleted (not the ones just added), and a second `confirm` request does not run it twice.
- A draw row on the bank (with and without a folder) still draws from the new questions after a replace; a published revision is unchanged.
- "Upload another file" on the check page keeps the replace mode.

---

### Task 1: Domain

**Files:**
- Modify: `app/domain/question_import.py`, `app/domain/banks.py`
- Test: `tests/domain/test_question_import.py`, `tests/domain/test_banks.py`

**Interfaces:**
- Produces in `banks.py`: `used_by(bank: QuestionBank) -> list[str]` (public name of the slugs that `_quizzes_using` returns; keep `delete` using it).
- Produces in `question_import.py`: `Target.replace: bool = False` (last field, default); `class ReplaceRefused(Exception)` with `.issues: list[Issue]`; `Outcome.removed: int = 0` (last field, default); `apply` handles `target.replace`.
- Behaviour: in `interpret`, when `target.replace` and the plan has any error issue, set `plan.refused` to `_("Replacing needs every row to be usable. Fix the rows listed and upload the file again; nothing was changed.")`. In `apply` with `target.replace`: remember `old_ids = list(bank.questions.values_list("pk", flat=True))` before saving; save the new questions as today; if any `_save_to_bank` returned an issue, raise `ReplaceRefused(issues)` inside the transaction so it rolls back; otherwise delete `bank.questions.filter(pk__in=old_ids)`, set `Outcome.removed`, and add `"replaced": True, "removed": N` to the audit details. A plan with no question still returns early, deleting nothing.

- [ ] **Step 1: Write the failing tests** in `tests/domain/test_question_import.py` (use `GOOD`, `plan_of`, `errors`, `make_bank`, `Target`, `ADMIN_ID`; build the target as `Target("bank", None, bank, replace=True)`)
  - `test_replace_adds_the_new_questions_and_deletes_the_old_ones`: bank with 2 questions imported earlier; replace with 3 rows; `bank.questions.count() == 3`, none of the old ids remain, `outcome.added == 3`, `outcome.removed == 2`
  - `test_replace_keeps_the_folders_and_the_bank_id`: bank with a folder `EU` holding a question; replace with a row whose `folder` is `EU`; the folder's pk is unchanged and holds the new question
  - `test_replace_with_an_error_row_is_refused_and_changes_nothing`: plan from `[GOOD, {"type": "choice", "prompt_cs": "Bez možností"}]` has `plan.refused`; `apply` is not needed; old questions still exist after `apply(plan, target, ...)` (which returns early on a refused plan: assert `outcome.added == 0` and the old count is the same; if `apply` does not guard `plan.refused`, guard it: a refused plan applies nothing)
  - `test_replace_rolls_back_when_saving_fails`: monkeypatch `question_import._save_to_bank` to return an `Issue(2, "folder", "x", True)` for the second question; `pytest.raises(question_import.ReplaceRefused)`; the old questions remain and no new one exists
  - `test_replace_with_no_usable_question_deletes_nothing`: a plan with no questions (only an ignored quiz row or an empty file) leaves the old questions
  - `test_replace_writes_counts_only_to_the_audit`: the `import.applied` event has `details["replaced"] is True`, `details["removed"] == 2` and no question text
- [ ] **Step 2: Write the failing test** in `tests/domain/test_banks.py`: `test_used_by_names_the_quizzes_that_draw_from_a_bank` (a quiz with a row; `banks.used_by(bank) == [slug]`; an unused bank gives `[]`)
- [ ] **Step 3: Run to verify failure**
  Run: `uv run pytest tests/domain/test_question_import.py tests/domain/test_banks.py -q -k "replace or used_by"`
  Expected: FAIL (no `replace`, no `used_by`)
- [ ] **Step 4: Implement** the interface above.
- [ ] **Step 5: Run**
  Run: `uv run pytest tests/domain -q`
  Expected: PASS
- [ ] **Step 6: Commit** `git add app/domain tests/domain docs/superpowers && git commit -m "feat(import): replace the questions of a bank (domain)"` with the attribution lines from the system reminder.

---

### Task 2: Pages

**Files:**
- Modify: `app/api/admin_import.py`, `app/api/jinja2/admin/bank.html`, `app/api/jinja2/admin/import_upload.html`, `app/api/jinja2/admin/import_check.html`, `app/api/jinja2/admin/import_report.html`
- Test: `tests/api/test_import.py`

**Interfaces:**
- Consumes: `Target(..., replace=True)`, `ReplaceRefused`, `Outcome.removed`, `banks.used_by` (Task 1).
- Produces: target value `bank_replace:<uuid>` accepted by `_parsed_target`, `_target_of` (returns `Target("bank", None, bank, replace=True)`), `_target_value`, `_target_label` ("Replace the questions of the bank %(name)s"). The check context gets `replace` (dict or None): `{"removed": <count of bank questions now>, "quizzes": <banks.used_by(bank)>}`. `_confirmed` catches `ReplaceRefused`: `plan.issues.extend(error.issues)`, `plan.refused = _("A row could not be saved, so nothing was replaced.")`. `_report` adds `"removed"`. The bank page shows a link "Replace questions" (`?target=bank_replace:<id>`) when `can_import` and the bank has questions.

- [ ] **Step 1: Write the failing tests** in `tests/api/test_import.py` (look at the existing bank-import tests for the upload and confirm helpers and reuse them)
  - `test_the_bank_page_offers_replacing_only_with_questions`: a bank with one question shows `target=bank_replace:<id>`; an empty bank does not
  - `test_replace_check_page_shows_the_effect_and_the_quizzes`: upload a valid file to `?target=bank_replace:<id>` on a bank with 2 questions drawn by a quiz with slug `pouziva-banku`; the check page contains the slug, the number 2, and the confirm button label "Replace the questions"; no bank question changed yet
  - `test_confirming_a_replace_swaps_the_questions_and_the_report_counts`: confirm; the bank holds only the file's questions, the report page contains the removed count, and the draw row of the quiz still has `usable == file's count`
  - `test_a_file_with_an_error_row_is_refused_on_the_check_page`: check page shows the refusal text and no confirm button; the bank is unchanged
  - `test_upload_again_keeps_the_replace_mode`: the "Upload another file" link on the check page contains `bank_replace:`
  - `test_a_published_revision_keeps_its_copies_after_a_replace`: publish a quiz with a draw row, replace the bank, `authoring.latest_published(quiz).snapshot_json` is unchanged and `authoring.banks_changed(quiz) is True`
- [ ] **Step 2: Run to verify failure**
  Run: `uv run pytest tests/api/test_import.py -q -k "replace"`
  Expected: FAIL
- [ ] **Step 3: Implement** the interface above; templates: the upload page already prints `target_label`; the check page adds a block when `replace` is set (removed count, quizzes list or "No quiz draws from this bank.", the note that published questions of those quizzes stay and the row shows an unpublished change) and changes the button label; the report page adds "Questions removed: %(count)s" when `report.removed`.
- [ ] **Step 4: Run**
  Run: `uv run pytest tests/api tests/test_wiring.py -q`
  Expected: PASS (no new route, so `test_request_limits` is unchanged)
- [ ] **Step 5: Translations**: `make messages`; fill cs and uk for every new string of the api and domain catalogues with `tools`-style editing (read the entries with empty `msgstr`; Babel `read_po` / `write_po(width=0, omit_header=True, ignore_obsolete=True)`); run `uv run pytest tests/test_translations.py -q`.
- [ ] **Step 6: Commit** `git add app tests && git commit -m "feat(import): a page to replace the questions of a bank"`; stage only `.po` and `.mo` of the api and domain catalogues, not the unrelated `.mo` noise.

---

### Task 3: Documentation and checks

**Files:**
- Modify: `docs/_architecture/acceptance-criteria.md`, `docs/_architecture/README.md`, `docs/_architecture/adr/0045-csv-one-file-and-failed-images.md`, `app/domain/CLAUDE.md`
- Test: `tests/test_docs.py` (a test must name AC-165 in its docstring: put `"""AC-165: …"""` in `test_confirming_a_replace_swaps_the_questions_and_the_report_counts` and `test_replace_rolls_back_when_saving_fails`)

- [ ] **Step 1: AC-165** after AC-164: "Import can replace the questions of a bank" — the bank page offers it, the check page shows how many questions are deleted and added and which quizzes draw from the bank, any error row refuses it, a save failure changes nothing, folders and the bank id stay so draw rows keep working, published revisions keep their copies, the audit holds counts only; related FR-41, ADR-0045; stage D. README range to AC-165. Addendum "Replace (addendum 2026-11-12)" to ADR-0045; one sentence in `app/domain/CLAUDE.md` under `question_import.py`.
- [ ] **Step 2: Run** `uv run pytest tests/test_docs.py -q` — Expected: PASS
- [ ] **Step 3: Run** `make quality` — Expected: exit 0
- [ ] **Step 4: Browser check** on a throwaway instance (not the user's stacks): bank with the 40-question CSV and a quiz row; replace with the same file (40 → 40, no duplicates); a file with one bad row is refused; check page and report at 1280 px light and 390 px dark; the bank page link; the quiz editor shows the unpublished-change notice after publishing. Report what was not seen in a browser.
- [ ] **Step 5: Commit** `git add docs app/domain/CLAUDE.md tests && git commit -m "docs: replacing the questions of a bank (AC-165, ADR-0045)"`

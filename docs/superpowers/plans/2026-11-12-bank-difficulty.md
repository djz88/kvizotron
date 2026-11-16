# Difficulty of bank questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A bank question carries a level (`easy`, `normal`, `hard`) as a reserved tag, and a draw row can ask for one level or a random mix.

**Architecture:** The level lives in the existing `BankQuestion.tags`; no migration. `banks.py` owns the levels, the "no level means normal" rule and the one-level validation; the draw row stores a new `difficulty` key that `_matching` filters on together with folder and tag. Import, the bank question form and the draw form call the same domain helpers.

**Tech Stack:** Django, Jinja2, pytest, Babel catalogues (`make messages`).

**Spec:** `docs/superpowers/specs/2026-11-12-bank-difficulty-design.md`

## Global Constraints

- Level values are exactly `easy`, `normal`, `hard`, compared with `banks.normal_tag`; they stay English in stored data in every language.
- No level tag means `normal`, decided when the pool is built, never written into `tags`.
- A draw row has `difficulty` of `""` (random mix, also a row without the key), `easy`, `normal` or `hard`. A level, a folder and a tag must all match when set.
- A question with more than one level tag is refused (import row error naming column `tags`; form error on `tags`). Other tags stay free.
- User-facing strings go through `gettext` (domain catalogue in `app/domain/locale/`, api catalogue in `app/api/locale/`); cs: Snadná, Normální, Těžká, Náhodný mix; uk: Легка, Звичайна, Складна, Випадковий мікс.
- Docs are English; IDs stay stable: new criteria are AC-163 and AC-164, the README range becomes `AC-01…AC-164`.
- No inline scripts or styles, every admin POST keeps CSRF (unchanged here: the draw form already has both).
- A published revision keeps its copies (AC-32); only drafts change.

## Review Focus

- A question tagged `Easy` or ` HARD ` (case and spaces) still matches the dropdown; a question tagged only `EU` matches `normal`.
- A draw row saved before this change (no `difficulty` key) opens in the editor with `Random mix` and still draws from the whole pool.
- A question tagged `easy,hard` arriving from a bank that already holds it (saved before the rule) does not crash the pool: it matches both levels.
- The row label, publication problems and the change overview show the level only when one is set.
- Import of a bank file with one bad level row skips that row, keeps the others and names column `tags`.

---

### Task 1: Levels in the domain

**Files:**
- Modify: `app/domain/banks.py`, `app/domain/authoring.py`, `app/domain/revision_diff.py`
- Test: `tests/domain/test_banks.py`, `tests/domain/test_draws.py`

**Interfaces:**
- Produces in `app/domain/banks.py`:
  - `LEVELS: tuple[str, ...] = ("easy", "normal", "hard")`
  - `class MoreThanOneLevel(Exception)`
  - `levels_of(tags: Sequence[str]) -> set[str]`: the level tags present (via `normal_tag`), or `{"normal"}` when none
  - `check_one_level(tags: Sequence[str]) -> None`: raises `MoreThanOneLevel` when two different level tags are present
  - `level_label(level: str) -> str`: translated label of a level, `""` for `""`
  - `level_choices() -> list[tuple[str, str]]`: `[("", Random mix), ("easy", Easy), ("normal", Normal), ("hard", Hard)]` translated
- Changes: `banks._matching` honours `row.get("difficulty", "")`; `banks.save_question` calls `check_one_level(tags)` before saving; `authoring.save_draw(..., difficulty: str = "")` stores `difficulty` in the row (reject a value not in `("", *LEVELS)` with `ValueError`).
- Row labels: `authoring._row_label` and `revision_diff._draw_text` add `level_label(row["difficulty"])` after folder path and tag when `row.get("difficulty")` is set.

- [ ] **Step 1: Write the failing tests** in `tests/domain/test_banks.py`
  - `test_levels_of_defaults_to_normal_and_ignores_case`: `levels_of(["EU"]) == {"normal"}`, `levels_of([" Hard "]) == {"hard"}`, `levels_of(["easy", "EU"]) == {"easy"}`
  - `test_two_levels_on_one_question_are_refused`: `check_one_level(["easy", "hard"])` raises `MoreThanOneLevel`; `check_one_level(["easy", "EASY"])` and `check_one_level(["EU"])` do not; `add_bank_question(bank, tags=("easy", "hard"))` raises `MoreThanOneLevel` and no `BankQuestion` exists
  - `test_a_row_with_a_level_draws_only_that_level`: bank with questions tagged `("easy",)`, `("hard",)`, `("EU",)` (normal by default) and `("normal",)`; rows `{"bank_id": str(bank.id), "tag": "", "difficulty": level, "points": 1}`; `banks.usable_count(row, ["cs"])` is `(1, 1)` for `easy` and `hard`, `(2, 2)` for `normal`, and `(4, 4)` for `""` and for a row without the key
  - `test_level_and_tag_must_both_match`: questions `("EU", "easy")` and `("US", "easy")`; row with `tag="EU"`, `difficulty="easy"` gives `(1, 1)`
  - `test_a_question_with_two_level_tags_saved_earlier_matches_both`: create it with `BankQuestion.objects.filter(...).update(tags=["easy", "hard"])` after saving it plainly; rows for `easy` and `hard` each count it
- [ ] **Step 2: Write the failing tests** in `tests/domain/test_draws.py` (or `test_banks.py` if the draw tests live there)
  - `test_save_draw_stores_and_refuses_a_difficulty`: `authoring.save_draw(quiz, None, bank_id=..., tag="", count=1, points=1, position=0, difficulty="hard")` stores `"hard"` in `authoring.editable_draws(quiz)[0]["difficulty"]`; `difficulty="impossible"` raises `ValueError`; omitting it stores `""`
  - `test_row_label_and_change_overview_show_the_level_only_when_set`: a row with `difficulty="easy"` gives a publication problem label and `revision_diff` text containing `banks.level_label("easy")`; a row without it contains no level label
- [ ] **Step 3: Run them to verify they fail**
  Run: `uv run pytest tests/domain/test_banks.py tests/domain/test_draws.py -q`
  Expected: FAIL (`levels_of`, `LEVELS`, `difficulty` not defined)
- [ ] **Step 4: Implement the interface above** in `banks.py`, `authoring.py`, `revision_diff.py`. `_matching` keeps its folder and tag filters and adds: when `row.get("difficulty")`, a question stays only if `row["difficulty"] in levels_of(q.tags)`. Use `gettext` for labels.
- [ ] **Step 5: Run the tests**
  Run: `uv run pytest tests/domain -q`
  Expected: PASS
- [ ] **Step 6: Commit**
  `git add app/domain tests/domain && git commit -m "feat(banks): levels of bank questions and a level on the draw row"`

---

### Task 2: Import refuses two levels and documents the rule

**Files:**
- Modify: `app/domain/question_import.py`, `app/providers/csv_io/sample/csv-format.md`, `app/providers/csv_io/sample/quiz-sample.csv`
- Test: `tests/domain/test_question_import.py`, plus the test that pins the guide files if one exists (`grep -rn "csv-format" tests`)

**Interfaces:**
- Consumes: `banks.check_one_level`, `banks.MoreThanOneLevel` (Task 1).
- Changes: `_question` (where `tags=[...]` is built, around `question_import.py:254`) calls `banks.check_one_level(tags)` and on `MoreThanOneLevel` raises `_RowProblem("tags", _("A question can have only one of the tags easy, normal and hard."))`.

- [ ] **Step 1: Write the failing tests** in `tests/domain/test_question_import.py`
  - `test_two_levels_in_the_tags_column_is_a_row_error`: `plan_of([GOOD | {"tags": "EU, easy, hard"}, GOOD], Target("bank", None, make_bank()))` has exactly one error whose `column == "tags"` (use the `Issue` fields the file already asserts on) and the second row is kept
  - `test_a_single_level_or_none_imports`: rows with `tags` `"easy"`, `"EU"` and `""` give no errors
  - `test_apply_keeps_the_level_tag_without_adding_normal`: after `apply`, a row with `tags=""` has `tags == []` (the rule is applied when drawing)
- [ ] **Step 2: Run to verify failure**
  Run: `uv run pytest tests/domain/test_question_import.py -q -k "level"`
  Expected: FAIL on the first test
- [ ] **Step 3: Implement the check** in `_question`.
- [ ] **Step 4: Document the rule** in `csv-format.md`: change the `tags` row to say comma separated, used only in a bank, may hold one of `easy`, `normal`, `hard` (a question with none counts as `normal`, more than one is a row error). Add a `normal` and an `easy` tag to two rows of `quiz-sample.csv` only if the sample has a `tags` value today; otherwise leave the sample and say so in the commit message. Update any test that pins the guide text.
- [ ] **Step 5: Run the tests**
  Run: `uv run pytest tests/domain tests/api/test_admin_import.py -q`
  Expected: PASS (use the real file name for the import page tests: `ls tests/api | grep import`)
- [ ] **Step 6: Commit**
  `git add app tests && git commit -m "feat(import): one level per question and the default level in the file guide"`

---

### Task 3: Forms and pages

**Files:**
- Modify: `app/api/admin_forms.py` (`DrawForm`, `BankQuestionForm.clean_tags`), `app/api/admin_banks.py` (`_save_draw`, `draw_edit` initial), the builder of draw rows for the quiz editor (find it with `grep -rn 'kind.*draw' app/api/*.py`) and `app/api/jinja2/admin/quiz_edit.html`
- Test: `tests/api/test_admin_banks.py`

**Interfaces:**
- Consumes: `banks.level_choices()`, `banks.level_label()`, `banks.check_one_level()`, `authoring.save_draw(..., difficulty=...)` (Task 1).
- Produces: `DrawForm.difficulty` (`forms.ChoiceField`, `required=False`, label "Difficulty", help text "A random mix draws every level. A question without a level counts as normal.", choices set in `__init__` from `banks.level_choices()`); the quiz editor draw row shows the level label after the tag in its `<small>` line when set.

- [ ] **Step 1: Write the failing tests** in `tests/api/test_admin_banks.py` (use the existing `draw_form`, `bank_with`, `add_row`, `logged_in`, `text` helpers)
  - `test_draw_form_offers_the_four_difficulties`: GET the new-draw page; the page contains `name="difficulty"` and the four option values `""`, `easy`, `normal`, `hard`
  - `test_adding_a_row_with_a_difficulty`: POST `draw_form(bank, difficulty="hard")`; `authoring.editable_draws(quiz)[0]["difficulty"] == "hard"`; POST without the field stores `""`
  - `test_an_unknown_difficulty_is_refused`: POST `difficulty="impossible"` gives 200 and no row
  - `test_editing_a_row_without_a_difficulty_shows_the_random_mix`: `add_row` row has no key; the edit page marks the empty option `selected` and saving it again stores `""`
  - `test_the_row_shows_its_level_in_the_quiz_editor`: a row with `difficulty="easy"` shows `banks.level_label("easy")` on `/admin/quizzes/<id>/edit`; a row without shows none of the three labels
  - `test_two_level_tags_are_refused_by_the_bank_question_form`: POST `QUESTION | {"tags": "easy, hard"}` gives 200, shows the error text and creates no question; `{"tags": "easy, EU"}` creates it
- [ ] **Step 2: Run to verify failure**
  Run: `uv run pytest tests/api/test_admin_banks.py -q -k "difficult or level"`
  Expected: FAIL
- [ ] **Step 3: Implement**: the field and its choices in `DrawForm`; pass `data["difficulty"]` in `_save_draw`; add `"difficulty": row.get("difficulty", "")` to the edit initial; call `banks.check_one_level(tags)` in `BankQuestionForm.clean_tags` and turn `MoreThanOneLevel` into `forms.ValidationError(_("A question can have only one of the tags easy, normal and hard."))`; build the label for the editor row and print it in `quiz_edit.html` next to `row.tag`. Update the help text of `BankQuestionForm.tags` to mention that `easy`, `normal` or `hard` sets the difficulty.
- [ ] **Step 4: Run the tests**
  Run: `uv run pytest tests/api -q`
  Expected: PASS (`tests/test_wiring.py` and `tests/api/test_request_limits.py` unchanged: no new route)
- [ ] **Step 5: Commit**
  `git add app tests && git commit -m "feat(banks): a difficulty dropdown on the draw row"`

---

### Task 4: Documentation and translations

**Files:**
- Modify: `docs/_architecture/acceptance-criteria.md`, `docs/_architecture/README.md` (AC range), `docs/_architecture/adr/0041-draw-rows-and-flow-settings.md`, `docs/_architecture/adr/0045-csv-one-file-and-failed-images.md`, `app/domain/CLAUDE.md`, `app/domain/locale/{cs,uk}/LC_MESSAGES/django.po`, `app/api/locale/{cs,uk}/LC_MESSAGES/django.po`
- Test: `tests/test_docs.py` (existing checks: AC ids defined, README range)

- [ ] **Step 1: Add AC-163 and AC-164** after AC-162 in `acceptance-criteria.md`, in the table's format. AC-163 "A draw row can ask for a difficulty": the row offers Random mix, Easy, Normal, Hard; a question carries its level as the tag `easy`, `normal` or `hard`, a question without one counts as normal, a level and a folder and a tag must all match, a row written earlier means a random mix, a published revision keeps its copies; related FR-18, ADR-0041; stage D. AC-164 "Import of difficulty": a bank file's `tags` may hold one level; none means normal and the file guide says so; more than one skips that row with an error naming `tags`, the bank question form refuses it; related FR-41, ADR-0045; stage D.
- [ ] **Step 2: Add the addenda**: a bullet "Difficulty (addendum 2026-11-12)" to ADR-0041 (row key `difficulty`, matching, label) and ADR-0045 (the rule for `tags`), in the style of the existing addenda; one sentence in `app/domain/CLAUDE.md` under `banks.py`; README range `AC-01…AC-164`.
- [ ] **Step 3: Translations.** Run `make messages`, fill `msgstr` in cs and uk for every new string (labels above; the field label "Difficulty" is cs "Obtížnost", uk "Складність"; the two help texts and the two error texts in clear Czech and Ukrainian; cs error: "Otázka může mít jen jeden ze štítků easy, normal a hard."). Unrelated `.mo` noise in other catalogues stays unstaged: stage only the files this change touches.
- [ ] **Step 4: Run the whole check**
  Run: `make quality`
  Expected: lint, tests (all) and gitleaks pass; report the test count
- [ ] **Step 5: Browser check** with the `kvizotron-browser-walkthrough` skill on a throwaway instance (not the user's `kvizotron-browser` or the `kvizotron-tmp` stack): add a draw row with each difficulty at 1280 px light and 390 px dark, open an old row, import `kviz_eu_cr_banka.csv` into a new bank (15 easy, 19 normal, 6 hard), publish a quiz with a `Hard` row of 5 and play it. Report what was not seen in a browser.
- [ ] **Step 6: Commit**
  `git add docs app tests && git commit -m "docs: difficulty of bank questions (AC-163, AC-164, ADR-0041, ADR-0045)"`

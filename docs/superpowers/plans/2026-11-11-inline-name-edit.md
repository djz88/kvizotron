# Inline Name Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pencil next to a name turns it into a field with Save and Cancel (HTMX, with full-page links as the fallback) for the names of a bank, a folder, a quiz, a reward and a participant's nickname, and the bank page says which languages a bank's questions have.

**Architecture:** One component: a Jinja macro `admin/_inline_name.html`, a small helper `app/api/inline_name.py` that decides between a partial (HTMX) and a full page, and a script `inline-edit.js` for Enter, Esc and focus. Each place gives its own save route and its field; domain services do the saving.

**Tech Stack:** Django, Jinja2, HTMX (already loaded, 4xx responses already swap), pytest (`uv run pytest`), `make quality`, `make messages`.

**Spec:** `docs/superpowers/specs/2026-11-11-inline-name-edit-design.md`

## Global Constraints

- A pencil is an icon button with an accessible name containing the name it edits ("Edit name: …"); at least 44 px on a phone; focus goes to the field on open and back to the pencil on close; "saved" is announced in `role="status"`, a refusal in `role="alert"`. [spec]
- Enter saves, Esc cancels. Without JavaScript the pencil is a link to `?edit=name` on the host page and **Cancel** a link back; a refusal re-renders the host page with status 400 and keeps what was typed. [spec]
- Last one wins: no version check. [spec]
- Banks and folders have one name for all languages; a quiz and a reward are edited inline for the default language only, the other languages stay in their forms. [spec]
- A quiz rename makes a draft (`authoring.get_draft`) and says "visitors see it after publication". [spec]
- No inline styles or scripts; `hx-*` attributes are set on the element that needs them (`app/api/CLAUDE.md`). Every new POST route has `{{ csrf_input }}` and an entry in `ARGUMENTS` of `tests/api/test_request_limits.py` when it has a new URL argument; the script is in `SCRIPTS` (`app/api/rendering.py`) and used by a template. [spec, `CLAUDE.md`]
- Audit entries carry no names (existing `bank.renamed`, `bank.folder_renamed`, `reward.texts_saved`; new `participant.renamed`). [spec]
- Texts in cs and uk (`make messages`); a new AC per behaviour with its id in test docstrings (last id today: AC-159; the README range and `AC_NOT_NAMED_BY_A_TEST` follow the rules of `tests/test_docs.py`); docs by addenda. The unrelated `.mo` files stay unstaged. [`CLAUDE.md`]

## Review Focus

- A refused rename (empty, too long, a name a sibling has) shows its message next to the field and keeps the typed text, both with HTMX (400 partial) and without it (400 full page); the old name stays stored.
- A name with HTML (`<img src=x onerror=…>`) is shown escaped in the display, the field value and the accessible name of the pencil.
- A participant rename refuses a name another participant of the run holds when the run forbids equal names, refuses an empty name, and clears the cached scoreboard; the audit entry holds no name.
- A quiz rename of a quiz whose default language has no title yet, and of an archived quiz (409, nothing changed).
- A reward rename on a run that is not scheduled changes only texts (`rewards.save_texts`) and keeps the structure.
- Pressing Esc or **Cancel** restores the shown name without a request or with a harmless GET, and focus returns to the pencil.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/api/inline_name.py` (new) | `NameField` dataclass, `wants_partial(request)`, `render_field(request, field, status)` |
| `app/api/jinja2/admin/_inline_name.html` (new) | macro `inline_name(field, tag)` drawing the display with a pencil or the field with Save and Cancel |
| `app/api/assets/inline-edit.js` (new), `app/api/rendering.py` | Enter, Esc, focus; entry in `SCRIPTS` |
| `app/plugins/theme_default/assets/theme.css` | `.inline-name*` styles with theme tokens |
| `app/api/admin_banks.py`, `admin_urls.py`, `bank.html`, `_bank_languages` in `bank.html` | bank and folder names, languages |
| `app/api/admin_quizzes.py`, `_quiz_header.html` | quiz name |
| `app/api/admin_rewards.py`, `rewards.html` | reward name |
| `app/domain/participants.py`, `app/api/admin_runs.py`, `run.html` | nickname |
| `app/domain/banks.py` | `language_counts(bank)` |
| tests | `tests/api/test_inline_name.py` (new), `tests/api/test_admin_banks.py`, `tests/api/test_admin_quizzes*.py`, `tests/api/test_admin_rewards*.py`, `tests/domain/test_participants*.py`, `tests/domain/test_banks.py` |
| docs | `acceptance-criteria.md`, `modules/api-ui.md`, ADR addenda, `app/api/CLAUDE.md` |

---

### Task 1: The component and the name of a bank

**Files:**
- Create: `app/api/inline_name.py`, `app/api/jinja2/admin/_inline_name.html`, `app/api/assets/inline-edit.js`, `tests/api/test_inline_name.py`
- Modify: `app/api/rendering.py` (`SCRIPTS`), `app/plugins/theme_default/assets/theme.css`, `app/api/admin_banks.py` (`bank_page`, `_bank_page`), `app/api/admin_urls.py`, `app/api/jinja2/admin/bank.html`, `tests/api/test_request_limits.py` (if a new URL argument appears)

**Interfaces:**
- Produces, `app/api/inline_name.py`:
  - `@dataclass class NameField: label: str; field: str; value: str; save_url: str; edit_url: str; view_url: str; max_length: int; editing: bool = False; error: str = ""; note: str = ""; saved: bool = False`
  - `wants_partial(request: HttpRequest) -> bool` (header `HX-Request: true`)
  - `render_field(request: HttpRequest, field: NameField, status: int = 200) -> HttpResponse` (the macro as a partial)
- Produces, macro `inline_name(field: NameField, tag: str = "span")` in `admin/_inline_name.html`: a wrapper `<span class="inline-name" id="name-<field.field>-<id>">` holding the name (in `tag`) and a pencil `<a href="?edit=<field.field>" hx-get="{{ field.edit_url }}" hx-target="closest .inline-name" hx-swap="outerHTML" aria-label="…">✎</a>`, or, when `editing`, a `<form method="post" action="{{ field.save_url }}" hx-post=… hx-target="closest .inline-name" hx-swap="outerHTML">` with a text input (`maxlength`, `autofocus`, `aria-describedby` the message), **Save**, and a **Cancel** link (`href` the host page, `hx-get="{{ field.view_url }}"`).
- Bank routes: `admin_bank_name` at `banks/<uuid:bank_id>/name`: GET returns the display partial, or with `?edit=1` the field partial; POST saves (`banks.rename`) and returns the display partial with `saved=True` (HTMX) or a redirect to `admin_bank` (no HTMX); a refusal is a 400 with the field partial (HTMX) or the host page with the field open (no HTMX). The existing POST on `admin_bank` is removed with the old form. The host page opens the field when `?edit=name`.
- Validation: `BankForm.name` (1 to 120 characters, stripped).

- [ ] **Step 1: Write failing tests** in `tests/api/test_inline_name.py` (use `logged_in`, `make_bank`):
  - `test_the_bank_name_is_shown_with_a_pencil_and_the_old_form_is_gone`: page has `class="inline-name"`, an `<a>` with `href="?edit=name"`, `hx-get` and an `aria-label` that contains the bank name; no `name="name"` input and no full-width Save in "Name and removal"; **Delete the bank** is still there.
  - `test_edit_partial_and_full_page`: GET `…/name?edit=1` with `HX-Request: true` returns a fragment (no `<html`) with a form; GET `/admin/banks/<id>?edit=name` returns the full page with the field open and focus attribute.
  - `test_saving_through_htmx_returns_the_display_and_changes_the_name`: POST with `HX-Request`, name `"Nová"` → 200, fragment contains `Nová`, `role="status"`; `QuestionBank.name == "Nová"`; audit `bank.renamed` with `details_json == {}`.
  - `test_saving_without_htmx_redirects`.
  - `test_a_refusal_shows_the_message_and_keeps_the_text` (AC-160): names `""`, `"   "`, 121 characters → 400, with HTMX the fragment, without it the page; both contain `role="alert"` and the typed value; the stored name is unchanged.
  - `test_a_name_with_html_is_escaped_everywhere`: `<img src=x onerror=alert(1)>` appears as `&lt;img` in the display, the field value and the `aria-label`.
  - `test_the_script_is_loaded_and_used` (wiring): `inline-edit.js` is in `SCRIPTS` and `assets/inline-edit.js` exists.
- [ ] **Step 2: Run** `uv run pytest tests/api/test_inline_name.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `inline_name.py`, the macro and partial, the route and its URL (name `admin_bank_name`), and rebuild the top of `bank.html`: the heading becomes `{{ inline_name(name_field, "h1") }}` and "Name and removal" keeps only **Delete the bank**.
- [ ] **Step 4: Write `inline-edit.js`** (plain script, no inline code): on `keydown` inside `.inline-name form` Esc clicks the **Cancel** link; Enter submits (the form already does); after an `htmx:afterSwap` into `.inline-name` it focuses the input when the field is open, or the pencil when it was closed. Everything works without it.
- [ ] **Step 5: CSS** `.inline-name`, `.inline-name form` (inline flex, wraps on a phone, input and buttons in one row at 1280 px, stacked at 390 px), `.inline-name-pencil` (44 px target, theme tokens), `.inline-name-note`.
- [ ] **Step 6: Run** the new tests, `uv run pytest tests/api tests/test_wiring.py -q`. Expected: PASS.
- [ ] **Step 7: Commit** `feat(admin): inline editing of the name of a bank with a pencil`

---

### Task 2: The name of a folder, in its row and from inside it

**Files:**
- Modify: `app/api/admin_banks.py` (`folder_rename`, `_bank_page`), `app/api/admin_urls.py`, `app/api/jinja2/admin/bank.html`
- Test: `tests/api/test_admin_banks.py`, `tests/api/test_inline_name.py`

**Interfaces:**
- Consumes: Task 1 (`NameField`, `inline_name`, `render_field`, `wants_partial`).
- Produces: `admin_bank_folder_rename` (existing URL `banks/<bank>/folders/<folder>/rename`) now also answers GET (display, or the field with `?edit=1`) and POST returning the display partial or a redirect; a refusal (`bank_folders.FolderError`) is a 400. The row of a folder shows its name through `inline_name(field)` (the link to open the folder stays as the name, the pencil is beside it), the **Přejmenovat** field leaves the ⋮ menu, and the heading of the folder one is inside (`current.name` in the `h2`, and the last link of the trail) gets a pencil.

- [ ] **Step 1: Write failing tests:** `test_a_folder_row_has_a_pencil_and_no_rename_field_in_the_menu`; `test_the_folder_one_is_inside_can_be_renamed_from_its_heading`; `test_renaming_a_folder_through_htmx_and_without` (display partial / redirect, `bank.folder_renamed` audit with `details_json == {}`); `test_a_clashing_or_bad_folder_name_is_refused_inline` (`"obchod"` when a sibling `"Obchod"` exists, `"a/b"`, 81 characters → 400 with `role="alert"` and the typed text); `test_folder_names_are_escaped` (heading, field, accessible name).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** as above; keep the redirect target of a non-HTMX save as the page the admin came from (`next_folder`).
- [ ] **Step 4: Run** `uv run pytest tests/api -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(admin): inline editing of the name of a folder`

---

### Task 3: The name of a quiz

**Files:**
- Modify: `app/api/admin_quizzes.py` (new view next to `quiz_edit`), `app/api/admin_urls.py`, `app/api/jinja2/admin/_quiz_header.html`
- Test: `tests/api/test_admin_quizzes*.py` (the file that holds the settings tab tests; find it with `grep -ln "admin_quiz_settings" tests/api`), `tests/api/test_inline_name.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `admin_quiz_name` at `quizzes/<uuid:quiz_id>/name`, same GET/POST contract as the bank name; it changes `quiz.title[quiz.default_locale]` only (max 200, required here, trimmed), makes a draft (`authoring.get_draft`) when the value changed, refuses an archived quiz (409, nothing changed). The field has `note` = "Visitors see the new name after you publish." (shown beside the pencil and in the saved partial). The `<h1>` of `_quiz_header.html` is `inline_name(field, "h1")`; the title in the `<summary>` stays text.

- [ ] **Step 1: Write failing tests:** `test_the_quiz_header_has_a_pencil_and_the_note`; `test_renaming_changes_the_default_language_title_only_and_makes_a_draft` (cs default, en title unchanged, `authoring.has_draft(quiz)` true); `test_a_quiz_without_a_title_in_its_default_language_can_be_named`; `test_an_archived_quiz_is_not_renamed` (409, unchanged); `test_a_bad_quiz_name_is_refused_inline` (empty, 201 characters); escaping test.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Reuse `QuizContentForm` limits (200) through a tiny `QuizNameForm(forms.Form)` with `name = CharField(max_length=200)` in `admin_forms.py`.
- [ ] **Step 4: Run** `uv run pytest tests/api tests/domain -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(admin): inline editing of the name of a quiz`

---

### Task 4: The name of a reward

**Files:**
- Modify: `app/api/admin_rewards.py`, `app/api/admin_urls.py`, `app/api/jinja2/admin/rewards.html`
- Test: `tests/api/test_admin_rewards*.py` (find with `grep -ln "reward_rule" tests/api`), `tests/api/test_inline_name.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `admin_reward_rule_name` at `rewards/<uuid:rule_id>/name`, GET/POST as above, changing `texts_json["name"][default locale of the quiz]` through `rewards.save_texts` (it works on a run that is not scheduled, because it changes only texts; it refuses an archived quiz with 409). The row's `<summary>` keeps the name as text; the pencil is a button after the `<details>` summary line, outside it, drawing the same macro.

- [ ] **Step 1: Write failing tests:** `test_a_reward_has_a_pencil_beside_its_summary`; `test_renaming_a_reward_changes_only_the_default_language_name` (description and claim unchanged); `test_a_reward_of_a_running_run_can_be_renamed_and_keeps_its_structure`; `test_a_bad_reward_name_is_refused_inline` (empty, 81 characters, the limit of `rewards._TEXT_LIMITS["name"]`); `audit reward.texts_saved with details {}`; escaping.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/api tests/domain -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(admin): inline editing of the name of a reward`

---

### Task 5: The nickname of a participant

**Files:**
- Modify: `app/domain/participants.py`, `app/api/admin_runs.py` (`_attempt_table`, new view), `app/api/admin_urls.py`, `app/api/jinja2/admin/run.html`
- Test: `tests/domain/test_participants.py` (or the file with `name_is_taken` tests: `grep -ln "name_is_taken" tests/domain`), `tests/api/test_admin_runs*.py`

**Interfaces:**
- Produces, `app/domain/participants.py`:
  - `class NameRefused(Exception)` with `.code` in `{"empty", "too_long", "taken"}`
  - `rename(participant: Participant, name: str, *, admin_id: str) -> None`: strip; empty → `NameRefused("empty")`; longer than the model field (40) → `"too_long"`; `name_is_taken(run, name, exclude=participant)` → `"taken"`; sets `display_name` and `name_key` as `claim_name` does, leaves `name_dropped` alone; one transaction; audit `participant.renamed` (`entity_type="participant"`, `entity_id` the participant id, `details={}`); after commit `results.clear_board_cache(run.id)`.
  - `AttemptRow` gains `participant_id: UUID | None = None` (last field, default None).
- Produces, API: `admin_participant_name` at `runs/<uuid:run_id>/participants/<uuid:participant_id>/name`, GET/POST as above (404 for a participant of another run or a run of kind test). The "Name" cell of the table of attempts shows `inline_name` when the run keeps names (not stateless, has the row's participant).

- [ ] **Step 1: Write failing tests (domain):** `test_rename_sets_name_and_key_and_clears_the_scoreboard_cache`; `test_rename_refuses_empty_too_long_and_taken` (`DUPLICATE_NAMES` set to forbid and another participant with a finished attempt holds the name; without the rule the same name is allowed); `test_rename_audit_has_no_name`; `test_rename_leaves_name_dropped_alone`.
- [ ] **Step 2: Write failing tests (API):** `test_the_table_of_attempts_has_a_pencil_for_each_name`; `test_renaming_a_participant_through_htmx_and_without`; `test_a_refused_nickname_is_shown_inline` (400, `role="alert"`, typed text); `test_a_participant_of_another_run_is_a_404`; `test_a_stateless_run_has_no_pencils`; escaping.
- [ ] **Step 3: Run** them. Expected: FAIL.
- [ ] **Step 4: Implement** domain, then API. Add `participant_id` to `AttemptRow` rows in `attempt_rows`.
- [ ] **Step 5: Run** `uv run pytest tests -q -k "participant or admin_runs or attempt"`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(admin): an admin can rename the nickname of a participant`

---

### Task 6: Languages of a bank on its page

**Files:**
- Modify: `app/domain/banks.py`, `app/api/admin_banks.py` (`_bank_page`, `_question_rows`), `app/api/jinja2/admin/bank.html`, `app/plugins/theme_default/assets/theme.css`
- Test: `tests/domain/test_banks.py`, `tests/api/test_admin_banks.py`

**Interfaces:**
- Produces: `banks.language_counts(bank: QuestionBank, locales: Sequence[str]) -> dict[str, int]` (for each locale the number of questions complete in it, from `questions.complete_locales`; locales with 0 questions are omitted).
- The bank page shows, under the name, chips `cs 40 · en 40 · uk 12` (links with `?view_lang=<code>` that keep the current `folder` and `q`); the chosen language (default: the first with a count) sets the language of the question texts listed for the folder and its subfolders. A question without that language shows its first complete language and a mark (`aria-label` "not available in <code>"). Folder names and counts do not depend on it. The question row already lists the languages it is complete in.

- [ ] **Step 1: Write failing tests:** `test_language_counts` (one question cs only, one cs+uk → `{"cs": 2, "uk": 1}`); `test_the_bank_page_shows_language_chips_with_counts`; `test_the_chosen_language_sets_the_question_texts` (a question with different prompts per language shows the `uk` text with `?view_lang=uk`); `test_a_question_without_the_chosen_language_is_marked`; `test_chips_keep_the_folder_and_the_search`; unknown `view_lang` is ignored.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/api/test_admin_banks.py tests/domain/test_banks.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(banks): languages of a bank and a language of the question texts`

---

### Task 7: Translations, documentation, browser check, quality

**Files:**
- Modify: `app/api/locale/{cs,uk}/…`, `app/domain/locale/{cs,uk}/…`, `docs/_architecture/acceptance-criteria.md` (AC-160 inline names with HTMX and without, AC-161 nickname rename, AC-162 bank languages), `docs/_architecture/modules/api-ui.md`, addenda in the ADRs of banks (ADR-0041), branding or rewards where they own the name (ADR-0053 for rewards), `app/api/CLAUDE.md` (the component), `docs/_architecture/README.md` (range of AC ids)
- Test: the whole suite

- [ ] **Step 1: `make messages`**, fill every new `msgstr` in cs and uk (Edit name, Save, Cancel, "Visitors see the new name after you publish.", the nickname messages, the language texts), run it again; stage only the catalogues whose `.po` you changed and their `.mo`.
- [ ] **Step 2: Docs:** the AC rows with their ids in test docstrings; `api-ui.md` and the ADR addenda; the `AC_NOT_NAMED_BY_A_TEST` list only shrinks.
- [ ] **Step 3: `make quality`.** Expected: lint, tests, gitleaks and the tech-debt check pass.
- [ ] **Step 4: Browser check** with the `kvizotron-browser-walkthrough` skill on a **throwaway instance** (own database, a session cookie from `force_login`, no passwords): at 1280 px light and 390 px dark, with the mouse and with Tab, Enter and Esc: rename a bank, a folder (row and from inside), a quiz (note shown), a reward and a nickname; try an empty and a taken name; open a page with the script blocked to confirm the full-page fallback; open the screenshots, `errs` empty. Do not touch the `kvizotron-browser` stack or any other running instance.
- [ ] **Step 5: Commit** `docs(admin): translations, acceptance criteria and notes for inline names`

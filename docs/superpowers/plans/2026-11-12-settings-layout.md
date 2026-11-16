# Settings pages: order, compact rows and search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings alphabetical inside each group with dependants indented under their parent, a new Rewards group, two-column rows with radio buttons for short choices, the scoreboard columns as one block, and a bank-style search that never drops a value on save.

**Architecture:** Group membership stays in the catalogue and manifests (`group=`); the alphabetical order inside a group, the parent/child marks, the short column labels and the widget swap live in `app/api/admin_view.py`, which `group_fields` already feeds to every settings page. `_setting_groups.html` renders one `.setting-row` per field. Search is a GET `q` read by the two settings views and passed to `group_fields`, which marks non-matching fields instead of dropping them.

**Tech Stack:** Django, Jinja2, Pico CSS, pytest, Babel.

**Spec:** `docs/superpowers/specs/2026-11-12-settings-layout-design.md`

## Global Constraints

- No setting changes its values, default, scope or stored data; POST field names and values stay the same.
- A field that is not shown because of search is rendered with `hidden` and still submitted; only Basic view leaves fields out (ADR-0052, unchanged).
- Search folds with `app.domain.bank_folders.fold` (casefold + Latin diacritics) over label, help text and value labels in the active language; with `q` the Basic filter is off.
- Radios for a `ChoiceField` with at most 3 choices not counting the empty "Use global setting" one; otherwise a dropdown.
- No inline script or style (CSP); admin strings cs and en only; new strings through `gettext`.
- Order inside a group: alphabetical by translated label folded with `bank_folders.fold`; a dependant (`CHILD_OF`) follows its parent, dependants of one parent alphabetical, except `main`, `accent` which keep their order under `color_palette`; the columns block sorts as "Scoreboard columns"; fields of `BRANDING_PLACES` keep their form order.
- AC number: the next free one (AC-168 if the test-link plan's AC-167 has landed, else AC-167); README range follows.

## Review Focus

- A quiz override on a setting that does not match the search survives a save made from the search view.
- In Basic view a search finds an advanced setting; clearing the search brings Basic back.
- On the quiz page the "Use global setting" radio is checked when there is no override, and choosing it removes the override.
- A refused save (conflict between settings) re-renders with the right radio checked and the group open.
- A disabled module's settings do not break the order (no KeyError, no empty group); a dependant whose parent is missing still shows.

---

### Task 1: Groups and order

**Files:**
- Modify: `app/contracts/__init__.py` (`SETTING_GROUPS`), `app/plugins/rewards/manifest.py`, `app/plugins/results/manifest.py` (`revision_mode` → `technical`), `app/domain/settings.py` (`none_option` → `playing`), `app/api/admin_view.py`, `app/api/jinja2/admin/_setting_groups.html`
- Test: `tests/domain/test_setting_groups.py`, `tests/api/test_admin_view.py`

**Interfaces:**
- Produces: `SETTING_GROUPS = ("playing", "answers", "participants", "scoreboard", "rewards", "data", "look", "technical")`; `GROUP_LABELS["rewards"] = gettext_lazy("Rewards")`; `admin_view.CHILD_OF: dict[str, str]` (`page_size→navigation_mode`, `reveal_level→reveal_moment`, `duplicate_names→ask_name`, `scoreboard_live_names`, `scoreboard_unnamed` → `scoreboard_visibility`, `main`, `accent` → `color_palette`; a name starting `anonymous_label_` → `scoreboard_visibility`); `FieldGroup.children: set[str]` (names of fields drawn indented). `group_fields` sorts each group's fields by the Global Constraints rule; a dependant whose parent is not shown is sorted as a normal field.

- [ ] **Step 1: Failing tests**
  - `test_setting_groups.py`: update the `SETTING_GROUPS` tuple assertion; `test_rewards_none_option_and_revision_mode_moved`: `reward_source`, `reward_thresholds`, `winner_contact` are in `rewards`, `none_option` in `playing`, `revision_mode` in `technical`.
  - `test_admin_view.py` (fixture `showing_all`): `test_a_group_is_alphabetical_with_dependants_under_their_parent` — `group_fields` on `GlobalSettingsForm` in cs: for each group, the non-dependant labels are sorted by `fold`, and each dependant comes right after its parent (or a sibling dependant); same check in en; `test_order_follows_the_language` — the `playing` group order differs between cs and en for at least one pair, or assert two concrete neighbours in each language; `test_a_dependant_without_its_parent_is_sorted_normally` — Basic view with `navigation_mode` hidden is impossible (basic), so use a form without `navigation_mode` (delete the field) and check `page_size` sits alphabetically; `test_a_dependant_row_is_indented` — on `/admin/settings` the row of `page_size` has class `setting-child`, `navigation_mode` not.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_setting_groups.py tests/api/test_admin_view.py -q` — Expected: FAIL
- [ ] **Step 3: Implement.** Move the groups, add `CHILD_OF`, sort in `group_fields`; the existing `test_global_page_lists_groups_in_order` keeps checking the group order. Render `class="setting-row{% if field.name in group.children %} setting-child{% endif %}"` around each field. Run `tests/contracts/test_settings_rule.py` too (manifest group validation).
- [ ] **Step 4: Run** `uv run pytest tests/domain tests/api tests/contracts -q` — Expected: PASS
- [ ] **Step 5: Commit** `feat(settings): a Rewards group and a fixed order inside each group` (with the spec and plan).

---

### Task 2: Compact rows, radios and the columns block

**Files:**
- Modify: `app/api/admin_view.py`, `app/api/jinja2/admin/_setting_groups.html`, `app/api/jinja2/admin/settings.html`, `app/api/jinja2/admin/quiz_settings.html`, `app/plugins/theme_default/assets/theme.css`
- Test: `tests/api/test_admin_view.py`; tests that assert `<option … selected>` for a setting that becomes radios are rewritten to the radio markup (`<input type="radio" name="…" value="…" … checked>`), same value checked — a markup rewrite, not a weaker test.

**Interfaces:**
- Consumes: `FieldGroup`, `ORDER` (Task 1).
- Produces: `group_fields` swaps the widget of a qualifying `ChoiceField` to `forms.RadioSelect(choices=field.choices)`; `admin_view.COLUMNS = ("scoreboard_show_score", "scoreboard_show_percent", "scoreboard_show_time", "scoreboard_show_duration")` and `COLUMN_LABELS` (gettext "Score", "Percent", "Time submitted", "Duration"); `FieldGroup.columns: list[BoundField]` drawn as `<fieldset class="setting-columns"><legend>{{ _("Scoreboard columns") }}</legend>` at the place of the first column key.
- Row markup: `<div class="setting-row">` with `<div class="setting-label">` (label tag, or for radios `<span id="<auto_id>_label">` and the row `role="group" aria-labelledby`) and `<div class="setting-control">` (help, errors, widget).

- [ ] **Step 1: Failing tests** — `test_short_choices_are_radios` (global page: `shuffle_questions` is `type="radio"`, `navigation_mode` and `time_zone` are `<select`); `test_quiz_page_radio_follows_global_when_not_overridden` (the `value=""` radio of `shuffle_questions` is `checked`); `test_choosing_use_global_removes_the_override` (override `shuffle_questions`, POST `""` → `quiz_override` is `None`); `test_a_refused_save_keeps_the_chosen_radio` (POST a flow conflict → 200 page, the posted radio `checked`); `test_columns_are_one_block` (one `fieldset.setting-columns` holding the four names, legend text "Scoreboard columns").
- [ ] **Step 2: Run** `uv run pytest tests/api/test_admin_view.py -q` — Expected: FAIL
- [ ] **Step 3: Implement.** CSS: `.settings-form` (class on the settings `form-section`s) `max-width: 56rem`; `@media (min-width: 48rem)` `.setting-row { display: grid; grid-template-columns: minmax(0, 15rem) minmax(0, 1fr); gap: 0 1rem; }`; radio widget `display: flex; flex-wrap: wrap; gap: 0.25rem 1rem`; `.setting-child` indented `1.25rem` with a muted left border; rows with a select of more than 20 options (`time_zone`) or the colour fields span both columns. Tokens only, dark mode follows.
- [ ] **Step 4: Run** `uv run pytest tests/api -q` — Expected: PASS
- [ ] **Step 5: Commit** `feat(settings): two-column rows, radios for short choices, scoreboard columns together`

---

### Task 3: Search

**Files:**
- Modify: `app/api/admin_view.py`, `app/api/admin_settings.py`, `app/api/admin_quizzes.py`, `app/api/jinja2/admin/_setting_groups.html`, `app/api/jinja2/admin/_section_panel.html`, `app/api/jinja2/admin/settings.html`, `app/api/jinja2/admin/quiz_settings.html`
- Test: `tests/api/test_settings_search.py` (new)

**Interfaces:**
- Consumes: `group_fields`, `FieldGroup` (Tasks 1–2).
- Produces: `group_fields(..., query: str = "")`; with a folded non-empty query `basic` is ignored, each field gets `FieldGroup.unmatched: set[str]`, `FieldGroup.matched: bool`; template renders `hidden` on unmatched rows and on unmatched groups; panel lists only matched groups; context `query`. Matching text: label, help text, and every choice label of the field (`str(...)` in the active language), folded with `bank_folders.fold`.

- [ ] **Step 1: Failing tests**
  - `test_the_search_form_looks_like_the_bank` — `form.bank-search[role=search]` with `input type="search" name="q"` and a "Search" button on both pages.
  - `test_search_shows_matching_settings_and_hides_the_rest` — `?q=zebricek` (cs): row of `scoreboard_visibility` without `hidden`, row of `navigation_mode` with `hidden`, group `group-playing` hidden.
  - `test_search_finds_an_advanced_setting_in_basic_view` (no `showing_all`): `?q=` a word of the label of `tie_break_policy` shows its row.
  - `test_search_matches_help_and_value_labels`.
  - `test_nothing_found_says_so` — `?q=xyzxyz` → "No setting matches." and a "Clear the search" link without `q`.
  - `test_saving_from_the_search_view_keeps_hidden_overrides` (docstring `AC-<n>:`) — quiz with an override of `reveal_moment`; GET `/admin/quizzes/<id>/edit?q=zebricek`; collect every named `input`/`select` value of the behaviour form from the HTML (`html.parser`: checked radios/checkboxes, selected options, text values, `csrfmiddlewaretoken`); POST it → override of `reveal_moment` unchanged.
- [ ] **Step 2: Run** `uv run pytest tests/api/test_settings_search.py -q` — Expected: FAIL
- [ ] **Step 3: Implement**; the global form posts to `admin_settings` without `q`.
- [ ] **Step 4: Run** `uv run pytest tests/api -q` — Expected: PASS
- [ ] **Step 5: Translations** `make messages`, cs for the new api strings ("Rewards" → "Odměny", "Scoreboard columns" → "Sloupce žebříčku", "Score" → "Skóre", "Percent" → "Procenta", "Time submitted" → "Čas odeslání", "Duration" → "Doba trvání", "Search the settings" → "Hledat v nastavení", "No setting matches." → "Žádné nastavení neodpovídá.", "Clear the search" → "Zrušit hledání"); `uv run pytest tests/test_translations.py -q` — Expected: PASS
- [ ] **Step 6: Commit** `feat(settings): search the settings like the bank` with only the api catalogues.

---

### Task 4: Documentation and checks

- [ ] **Step 1:** AC "Settings are ordered, compact and searchable" (order with dependants, Rewards group, radios ≤3 values, columns block, search: fields, fold, Basic off, hidden rows still saved, nothing found); FR of settings, ADR-0052; stage D; README range. ADR-0052 addendum "Order, rows and search". `docs/_architecture/modules/api-ui.md` "Where things are set": groups of the moved settings. `docs/_architecture/plugins/rewards.md` and `results.md`: new group. `app/api/CLAUDE.md`: one line at "Přepínač a skupiny" (order in `admin_view.ORDER`, search marks `hidden`, never leaves out).
- [ ] **Step 2: Run** `uv run pytest tests/test_docs.py -q` then `make quality` — Expected: PASS, exit 0
- [ ] **Step 3: Browser check** on a throwaway instance: global settings, quiz settings and run plan at 1280 light cs and 390 dark; radios by keyboard; search `zebricek`, save, reload, override kept; Pico does not show `[hidden]` rows.
- [ ] **Step 4: Commit** `docs: settings order, compact rows and search (AC-<n>, ADR-0052)`

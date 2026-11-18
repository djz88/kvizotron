# UI foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Kvízotron its navigation, a fixed place for every setting, a state-driven quiz header, quiz descriptions, five colour palettes and a lively mobile-first public side.

**Architecture:** Rules go to `app/domain/`: `quiz_state.py` decides the main button, `settings.py` holds the palette, `authoring.py` gains `publish_and_open` and the description. `app/api/` renders them through shared partials. Colours are token blocks in the theme's stylesheet, selected by `data-palette` on `<html>`. Dropdowns are `<details>`, with one small script for narrow screens.

**Tech Stack:** Django 6.1, Jinja2, HTMX, Pico CSS 2.1 (vendored), SQLite, Babel catalogues.

**Spec:** `docs/superpowers/specs/2026-11-06-ui-foundation-design.md`

## Global Constraints

- No inline scripts or styles (CSP). No new dependency. No downloaded fonts.
- Every action works by keyboard and without JavaScript, at 360 px and on desktop, with no horizontal page scroll.
- Views stay thin. `app/domain` does not import `app/api`, and plugins import only `app.contracts` (`tests/test_layers.py`).
- New admin strings in cs and en, public strings in cs, en and uk (`make messages`, `tests/test_translations.py`). Source strings are English. Czech for `QuizRun` is **běh**, English **run**, Ukrainian **запуск**.
- Code identifiers stay: `QuizRun`, `round_outcome` and `RoundDecisionRequired` are not renamed.
- Run everything in the dev container, because host uv is older than the required 0.13: `uv run pytest ...`, `make quality` equivalents, and `make smoke` on the host.
- Docs in English, each fact in one place. Next free ids: `FR-51`, `FR-52`, `FR-53`, `AC-23`, `AC-24`, `AC-25`.

## Review Focus

1. Start after the draft changed since the page was shown: nothing is published and no run opens; the page shows again (test in Task 2).
2. Another admin opens a run during `Start the quiz`: the publication rolls back too and the admin sees the page again (Task 2).
3. Revisions published before this milestone have no `description` key: public pages, comparison, return to that revision and discard all work (Task 1).
4. A stored palette value no longer in the catalogue, or a page with an unknown `data-palette`: the page falls back to the default colours and stays readable (Task 5).
5. A quiz published in one language: the language switch shows its flag and offers nothing to change to, and no link leads to a language the quiz lacks (Task 4).

---

### Task 1: Quiz description

**Files:**
- Modify: `app/domain/models.py`, `app/domain/authoring.py`, `app/domain/revision_diff.py`, `tests/domain/helpers.py`
- Create: `app/domain/migrations/0005_quiz_description.py`
- Test: `tests/domain/test_description.py`

**Interfaces:**
- Produces: `Quiz.description: dict[str, str]`; snapshot key `description`; problem code `description_missing` with `locale` set.

- [ ] **Step 1: Write the failing tests** in `tests/domain/test_description.py`:
  - `test_missing_description_blocks_publication`: a quiz with `description={}` gives `Problem(None, "cs", "description_missing")` from `validate_for_publication`.
  - `test_each_selected_language_needs_a_description`: `locales=("cs","en")`, `description={"cs": "x"}` gives one problem with locale `en`.
  - `test_description_is_frozen_in_the_snapshot`: after `publish`, `revision.snapshot_json["description"] == {"cs": "x"}`, and changing `quiz.description` changes `snapshot_hash(quiz)`.
  - `test_discard_and_return_restore_the_description`: publish `{"cs": "a"}`, change to `{"cs": "b"}`, `get_draft`, `discard_draft` gives `{"cs": "a"}`; the same through `use_as_draft`.
  - `test_duplicate_copies_the_description`.
  - `test_old_snapshot_without_description_can_be_restored_and_compared`: remove the key from `snapshot_json` by a queryset update, then `use_as_draft` gives `quiz.description == {}` and `revision_diff.compare(old, new, locales)` does not raise and lists the new description.

- [ ] **Step 2: Run them.** `uv run pytest tests/domain/test_description.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.**
  - `description = models.JSONField(default=dict)  # locale -> text` on `Quiz`; migration via `makemigrations` with `DJANGO_SETTINGS_MODULE=tests.settings`.
  - `validate_for_publication`: same check as `title_missing`. `future_snapshot`: add `"description": quiz.description`. `_restore_quiz_fields`: `snapshot.get("description", {})`. `duplicate_quiz`: deep copy.
  - `revision_diff._quiz_fields`: a `FieldChange(_("Description"), locale, before, after)` loop reading `old.get("description", {})`.
  - `helpers.make_quiz`: default `description` per locale unless given, so existing tests keep publishing. A helper used by tests that need a quiz without a description passes `description={}`.

- [ ] **Step 4: Run all tests.** `uv run pytest -q`. Expected: PASS.

- [ ] **Step 5: Commit** `feat: add a translated description to quizzes`.

### Task 2: Main button rules and starting a quiz

**Files:**
- Create: `app/domain/quiz_state.py`
- Modify: `app/domain/authoring.py`, `app/domain/settings.py`
- Test: `tests/domain/test_quiz_state.py`, `tests/domain/test_publish_and_open.py`, `tests/domain/test_settings.py` (or the existing settings test file)

**Interfaces:**
- Produces:
  - `class MainAction(StrEnum)`: `START`, `START_AGAIN`, `PUBLISH_CHANGES`, `END_RUN`, `RESTORE`.
  - `class SecondaryAction(StrEnum)`: `PUBLISH_ONLY`, `DISCARD`, `END_RUN`, `DUPLICATE`.
  - `@dataclass(frozen=True) class QuizState`: `main: MainAction`, `secondary: tuple[SecondaryAction, ...]`, `has_changes: bool`, `published_no: int | None`, `open_run: QuizRun | None`, `last_run: QuizRun | None`, `archived: bool`, `needs_publication_page: bool`.
  - `quiz_state.of(quiz: Quiz) -> QuizState`.
  - `authoring.publish_and_open(quiz, *, admin_id, expected_hash=None) -> QuizRun`.
  - `settings.COLOR_PALETTE = "color_palette"`, `class Palette(StrEnum)` with `BLUE_TEAL = "blue_teal"`, `INDIGO_PINK = "indigo_pink"`, `VIOLET_ORANGE = "violet_orange"`, `GREEN_BLUE = "green_blue"`, `RED_PLUM = "red_plum"`; catalogue default `blue_teal`.

- [ ] **Step 1: Write the failing tests.**

```python
@pytest.mark.parametrize(("setup", "main", "secondary"), [
    ("never_published_draft", MainAction.START, (SecondaryAction.PUBLISH_ONLY,)),
    ("published_never_started", MainAction.START, ()),
    ("never_started_with_changes", MainAction.START, (SecondaryAction.PUBLISH_ONLY, SecondaryAction.DISCARD)),
    ("finished", MainAction.START_AGAIN, ()),
    ("finished_with_changes", MainAction.START_AGAIN, (SecondaryAction.PUBLISH_ONLY, SecondaryAction.DISCARD)),
    ("running_with_changes", MainAction.PUBLISH_CHANGES, (SecondaryAction.DISCARD, SecondaryAction.END_RUN)),
    ("running_no_changes", MainAction.END_RUN, ()),
    ("archived", MainAction.RESTORE, (SecondaryAction.DUPLICATE,)),
])
def test_main_action_follows_the_quiz_state(setup, main, secondary): ...
```

  Plus:
  - `test_quiz_with_no_draft_and_no_revision_goes_to_the_publication_page`: `needs_publication_page` is true for `make_quiz()`; false for `published_never_started`; true when a draft exists.
  - `test_publish_and_open_publishes_and_opens_together`: returns a run on the new revision; audit has `quiz.published` and `run.opened`.
  - `test_publish_and_open_keeps_nothing_when_a_run_is_already_open`: patch `authoring.open_run` to raise `RunAlreadyOpen`; the draft is still a draft and no new revision is published.
  - `test_publish_and_open_with_stale_hash_changes_nothing`: raises `StalePublication`, no run.
  - `test_palette_setting_defaults_and_override`: `resolve(COLOR_PALETTE) == "blue_teal"`, a quiz override beats global, and an invalid value raises `InvalidSettingValue`.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement.** `has_changes` is `authoring.has_draft`. `DISCARD` only with a draft and a published revision (today's `can_discard`). Never started means no rows in `quiz.runs`. `publish_and_open` wraps `publish` and `open_run` in one `transaction.atomic()`. Use `transaction.atomic` outermost so `RunAlreadyOpen` undoes the publication.

- [ ] **Step 4: Run all tests.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: decide the main quiz action in the domain and start a quiz in one step`.

### Task 3: Readable question type names

**Files:**
- Modify: `app/contracts/__init__.py`, `app/plugins/questions/choice_single/plugin.py`, `tests/contracts/question_type.py`, `tests/fixtures/demo_site/kvz_demo_question/question.py`, `tests/kernel/test_registry.py` (any stub question type), `docs/plugin-api.md`, `docs/_architecture/modules/contracts.md`, `app/domain/authoring.py`
- Test: contract suite

**Interfaces:**
- Produces: `QuestionTypePlugin.label(self) -> str`, translated under the active language; `authoring.missing_locales(question: Mapping, locales: Sequence[str]) -> list[str]`.

- [ ] **Step 1: Write the failing tests.** In `QuestionTypeContract`: `test_label_is_readable_text` asserts a non-empty `str` different from `plugin.id`. In the domain tests: `test_missing_locales_lists_languages_without_translation`: a question with cs only and locales cs, en gives `["en"]`; a complete one gives `[]`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** `ChoiceSingleQuestion.label` returns `_("Single correct answer")`. `missing_locales` reuses the logic of `_question_problems`, calling `validate_definition` per locale. Add a `label` to every stub that must satisfy the protocol. Catalogues: `make messages`.
- [ ] **Step 4: Run all tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: give question types a readable label`.

### Task 4: Page structure, administration and public navigation

The largest task: routes, forms and templates change together, and the tests read the HTML.

**Files:**
- Create: `app/api/admin_workspace.py`, `app/api/assets/nav.js`, `app/api/assets/flag-cs.svg`, `flag-en.svg`, `flag-uk.svg`, `app/api/jinja2/admin/_quiz_header.html`, `admin/_actions.html`, `admin/quiz_settings.html`, `admin/runs.html`, `public/base.html`, `public/how_it_works.html`, `public/about.html`, `public/privacy.html`
- Modify: `app/api/admin_quizzes.py`, `admin_runs.py`, `admin_revisions.py`, `admin_forms.py`, `admin_urls.py`, `public.py`, `play.py`, `rendering.py`, `app/urls.py`, all templates in `app/api/jinja2/`, `app/plugins/theme_default/jinja2/theme_default/layout.html`, `tests/api/*`, `tests/integration/*`
- Test: `tests/api/test_admin_layout.py`, `tests/api/test_public_layout.py`

**Interfaces:**
- Consumes: `quiz_state.of`, `authoring.publish_and_open`, `plugin.label()`, `authoring.missing_locales`, `settings.COLOR_PALETTE`.
- Produces:
  - `admin_workspace.workspace(quiz, tab, run_error=None) -> dict`, `quiz_title(quiz)`; tabs are `edit`, `runs`, `revisions`, `settings`.
  - `QuizContentForm` (titles, descriptions up to 300 characters, languages, default language), `QuizBehaviourForm` (slug, featured, every catalogue setting as override; the slug is disabled after the first publication), and `QuizForm` for new quizzes with slug plus content fields.
  - Layout blocks `body_class`, `main_class`, `bar`; `<html data-palette="{{ palette }}">`.
  - `page()` adds `palette = settings.resolve(COLOR_PALETTE, context.get("palette_quiz"))`. Only public quiz and play views pass `palette_quiz`.
  - CSS classes used by Task 5: `dropdown`, `site-bar`, `site-nav`, `quiz-head`, `quiz-title`, `quiz-meta`, `status-area`, `chip`, `chip-live`, `chip-draft`, `tabs`, `rows`, `panel`, `form-section`, `actions`, `hero`, `card`, `quiz-row`, `is-featured`, `score`.

- [ ] **Step 1: Write the failing tests** in `tests/api/test_admin_layout.py`:

```python
@pytest.mark.parametrize("tab", ["edit", "runs", "revisions", "settings"])
def test_quiz_tabs_are_shared_and_mark_the_current_one(logged_in, tab): ...
    # every tab link present; the current one has aria-current="page"

def test_run_page_belongs_to_the_runs_tab(logged_in): ...
def test_questions_tab_holds_no_settings(logged_in): ...
    # no name="slug", no name="revision_switch_policy", no "/archive"
def test_question_row_shows_type_points_and_missing_translation(logged_in): ...
    # locales cs,en, question in cs only: "Single correct answer", points, "en" tag
def test_settings_tab_has_three_parts_and_says_when_changes_apply(logged_in): ...
    # lang=en: "after you publish", "apply immediately", /archive, /duplicate
def test_saving_address_creates_no_draft_and_saving_title_does(logged_in): ...
def test_invalid_form_shows_the_settings_tab_with_the_error(logged_in): ...
def test_settings_tab_of_archived_quiz_has_no_forms_and_post_is_409(logged_in): ...
def test_runs_tab_shows_running_panel_and_history(logged_in): ...
def test_runs_tab_without_running_run_has_no_panel(logged_in): ...
def test_revisions_tab_lists_only_revisions(logged_in): ...
@pytest.mark.parametrize(("setup", "label"), [
    ("never_started", "Start the quiz"), ("finished", "Start again"),
    ("running_with_changes", "Publish changes"), ("running_no_changes", "End the run"),
    ("archived", "Restore from archive"),
])
def test_header_main_button_follows_the_state(logged_in, setup, label): ...
def test_start_with_changes_shows_overview_then_publishes_and_opens(logged_in): ...
    # GET publish?start=1 has hidden start=1; POST redirects to /admin/runs/<id>; revision published
def test_start_without_changes_posts_to_runs(logged_in): ...
def test_start_on_a_quiz_never_published_leads_to_the_publication_page(logged_in): ...
def test_stale_start_shows_the_page_and_opens_nothing(logged_in): ...
def test_publish_only_does_not_open_a_run(logged_in): ...
def test_end_run_asks_for_confirmation(logged_in): ...
    # GET /admin/runs/<id>/close is a confirm page; run still open; POST closes
def test_main_navigation_marks_the_current_section(logged_in): ...
def test_language_dropdown_shows_the_active_flag(logged_in): ...
def test_global_settings_page_offers_the_palette(logged_in): ...
def test_quiz_list_shows_the_same_tags(logged_in): ...
def test_no_template_carries_an_inline_style_or_script(): ...
```

  In `tests/api/test_public_layout.py`:

```python
@pytest.mark.parametrize("path", ["/how-it-works", "/about", "/privacy"])
@pytest.mark.parametrize("lang", ["cs", "en", "uk"])
def test_information_page_exists_in_every_language(client, path, lang): ...
def test_menu_links_are_on_every_public_page(client): ...
def test_home_shows_slogan_motto_and_quiz_description(client): ...
def test_quiz_page_shows_title_description_and_start(client): ...
def test_old_revision_without_description_still_shows_its_page(client): ...
def test_one_language_quiz_offers_no_other_language(client): ...
def test_two_language_quiz_links_only_its_languages(client): ...
def test_quiz_palette_applies_only_to_its_public_pages(client): ...
    # override indigo_pink: /q/<slug> has data-palette="indigo_pink"; / has blue_teal
def test_palette_applies_to_play_pages(client): ...
def test_flag_assets_are_served_as_svg(client): ...
```

  Update existing tests whose pages moved: `test_admin_settings.py` reads the override text from `/settings`; `test_admin_quiz_management.py` checks `"/questions/" not in html` on the archived page; `test_admin_revisions.py` moves round history checks to `/runs`; test posts of the quiz form split between `/edit` and `/settings`. Do not weaken an assertion, only move it.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement routes and views.**
  - `admin_urls`: `quizzes/<id>/runs` dispatches GET to `admin_runs.runs_page`, POST to `admin_quizzes.run_open`. `quizzes/<id>/settings` gets GET. `runs/<id>/close` gets GET, rendering `admin/confirm.html` with a cancel link to the run page.
  - `quiz_edit` POST takes `QuizContentForm`, makes a draft if changed, redirects to settings. `quiz_settings` POST takes `QuizBehaviourForm`, saves slug and featured, writes overrides as today, creates no draft, redirects to settings. Invalid forms re-render `settings_page` with status 200; archived gives 409.
  - `quiz_publish`: `start=1` from the query or form adds a hidden field, and POST calls `publish_and_open` and redirects to `admin_run`. `RunAlreadyOpen` re-renders the page with a message.
  - `admin_revisions.revisions` drops rounds; `admin_runs.runs_page` builds them.
  - `app/urls.py`: `how-it-works`, `about`, `privacy` go to `public.info_page`, each with `request.locale` and `PUBLIC_LOCALES`.
  - `public.asset`: serve `flag-*.svg` as `image/svg+xml`, and `nav.js`. Flags live in `app/api/assets`, not the theme as the spec says, so that a future theme does not have to supply them. Record this as a ruling.

- [ ] **Step 4: Implement templates.**
  - Theme layout: bar with `Kvízotron` and block `bar`; the slogan moves out of the layout into the home page.
  - `admin/base.html`: bar holds the main navigation, language switch and logout inside `<details class="site-nav" open>`.
  - `public/base.html`: the same structure with the menu; every public page extends it. `public/landing.html` has `hero` with slogan and motto, `quiz.html` has `hero` with title and description, `play.html` has no hero.
  - `_languages.html`: `<details class="dropdown">` whose summary is the active flag `<img alt="{name}">`, listing the other languages with flag and name; with no other language, no dropdown, only the flag.
  - `_quiz_header.html`: two rows from the spec inside `<details class="quiz-fold" open>` whose summary shows title and current tab; the tabs below.
  - `_actions.html`: renders the main button and secondary dropdown from `QuizState`. A `GET` target is a link with `role="button"`, a `POST` target is a form with `csrf_input`.
  - `nav.js` (referenced from `page()`, loaded with `defer`): on narrow screens (`matchMedia("(max-width: 48rem)")`) removes `open` from `.site-nav` and `.quiz-fold` on load. Without JavaScript they stay open, so all actions stay reachable.
  - Texts for info pages are in this task's templates, truthful for the current application (no registration; no answers or personal data in logs). `/privacy` says it covers the current version.

- [ ] **Step 5: Run all tests, then `make messages` and fill the catalogues.** Expected: PASS, including `test_request_limits.py` for new forms and routes and `test_security_headers.py`.

- [ ] **Step 6: Commit** `feat: new navigation, quiz header, tabs and public menu`.

### Task 5: Palettes and the look

**Files:**
- Modify: `app/plugins/theme_default/assets/theme.css`, `app/api/admin_forms.py` (labels), `app/plugins/theme_default/CLAUDE.md` if it exists, `app/plugins/CLAUDE.md`
- Test: `tests/plugins/test_palettes.py`, created next to other plugin tests, or `tests/test_palettes.py`

**Interfaces:**
- Consumes: `settings.Palette`, `data-palette`, classes from Task 4.
- Produces: tokens `--kvz-main`, `--kvz-second`, `--kvz-accent`, `--kvz-on-accent`, `--kvz-dark`, `--kvz-card`, `--kvz-text`; light and dark variants per palette.

- [ ] **Step 1: Write the failing tests.** The test parses `theme.css`, reading one comment-free block per palette and mode:

```python
@pytest.mark.parametrize("palette", list(settings.Palette))
def test_every_palette_has_light_and_dark_tokens(palette): ...

@pytest.mark.parametrize("palette", list(settings.Palette))
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_palette_text_reaches_wcag_aa(palette, mode):
    # text on card >= 4.5; on-accent on accent >= 4.5; white on main >= 4.5
    # white on both ends of the gradient >= 4.5 (motto and description are small text)

def test_default_tokens_equal_blue_teal(): ...
    # an unknown data-palette falls back to :root values
```

  `contrast(a, b)` is the WCAG relative luminance formula, in the test module.

- [ ] **Step 2: Run them.** Expected: FAIL.

- [ ] **Step 3: Implement `theme.css`.** Start from the spec's hex values and darken where the test demands. Selectors match Pico's specificity: `:root:not([data-theme="dark"]), [data-theme="light"]` and `@media only screen and (prefers-color-scheme: dark) { :root:not([data-theme]) }`. Map tokens onto `--pico-*` variables. Public body: gradient background, `.card` surface. Admin body: plain surface and dark bar. Answer rows: `#play fieldset label:has(input[type="radio"])` as full-width rows of at least 3.25rem, and `:has(input:checked)` filled with the accent. Tables become stacked rows below 48rem. `.dropdown` and `.quiz-fold` hide their summary above 48rem where the content is always shown. Visible focus. No motion beyond Pico's defaults.

- [ ] **Step 4: Run all tests.** Expected: PASS.

- [ ] **Step 5: Commit** `feat: add five colour palettes and the base look`.

### Task 6: Terminology, docs and full verification

**Files:**
- Modify: Python and template source strings with "round", all `locale/*/django.po`, `deploy/smoke.sh`, `docs/_architecture/roadmap.md`, `modules/api-ui.md`, `modules/domain.md`, `data-model.md`, `plugins/theme-default.md`, `acceptance-criteria.md`, `README.md`, `CLAUDE.md`, `app/api/CLAUDE.md`, `tests/CLAUDE.md`
- Test: `tests/test_translations.py`

- [ ] **Step 1: Write the failing test** in `tests/test_translations.py`:

```python
def test_catalogues_do_not_use_the_old_word_for_a_run():
    # msgid and msgstr across all catalogues; regex (?i)\b(rounds?|kolo|kola|kolu|kole|раунд\w*)\b
```

- [ ] **Step 2: Run it.** Expected: FAIL.

- [ ] **Step 3: Rename.** "Open round" and similar become "run" in sources, `běh` in cs, `запуск` in uk. `make messages`. Update tests that read these strings.

- [ ] **Step 4: Update docs.**
  - `roadmap.md`: add row `B1.5 UI foundation`, progress indicator to B3, moving the palette list to the theme and custom colours to D1, finishing `FR-05` to D1.
  - `api-ui.md`: new `FR-51` (navigation and the "Where things are set" table from the spec), new `FR-53` (palettes), HTTP surface, `Spustit` flow.
  - `domain.md`: new `FR-52` (description), the state table reference to `quiz_state.py`, a line that older docs say "round" for a run.
  - `data-model.md`: `quiz.description`. `README.md` requirement map. `acceptance-criteria.md`: `AC-23` main button, `AC-24` description, `AC-25` palette override and contrast. `CLAUDE.md` status line, and `app/api/CLAUDE.md` notes on `nav.js`, `palette_quiz` and `public/base.html`.

- [ ] **Step 5: Run the checks.** Dev container: ruff, mypy, pytest, gitleaks, `tech-debt-check`. Host: `make smoke`. Extend `deploy/smoke.sh`: `/privacy` returns 200, and `/admin/quizzes/<id>/runs` returns 200 for the admin. Expected: all pass.

- [ ] **Step 6: Browser walkthrough** with Playwright against the Compose stack, at 360 px and 1280 px, in light and dark mode: create a quiz, add a question, `Start the quiz`, play on a phone width, change a question, `Publish changes`, `End the run`, `Start again`, change palette globally and per quiz; keyboard only for the dropdowns; JavaScript off for one pass. Check that no console errors appear and `document.documentElement.scrollWidth <= innerWidth` on each page. Send screenshots to the user.

- [ ] **Step 7: Commit** `docs: record the UI foundation, and use "run" in the interface`.

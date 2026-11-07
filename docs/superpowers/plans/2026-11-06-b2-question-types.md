# B2 Question types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single question type with Výběr and Přiřazení, with images, points, two scoring strategies, sources and an editor that does not lose or duplicate work.

**Architecture:** Question types grade answers (`grade`), strategies only weigh the grade. Images go through a new `media.local` provider behind a `media_storage` port; plugins see only asset ids. The API draws the fields common to all types around each plugin's form. Everything works without JavaScript; three small scripts improve it.

**Tech Stack:** Django 6.1, Jinja2, HTMX, Pico CSS, SQLite, Pillow (new, pinned, ADR-0028).

**Spec:** `docs/superpowers/specs/2026-11-06-b2-question-types-design.md`

## Global Constraints

- Branch `feat/b2-question-types`. Run tests in the dev container, because host uv is older than 0.13.
- Green field: no compatibility with existing data; `choice.single` disappears.
- Plugins import only `app.contracts` (`tests/test_layers.py`). No inline scripts or styles. Pillow is the only new dependency.
- Every type works by keyboard and without JavaScript, at 360 px and on desktop.
- Admin strings in cs and en, public strings in cs, en and uk (`make messages`). Czech for `QuizRun` is běh.
- Limits: 15 MB per image, SVG and GIF 5 MB; stored raster WebP, longest side 1600 px, at most 700 KB. Options up to 6, items 2 to 8, points 1 to 100, sources up to 10 lines of 300 characters, per ADR-0028 and the spec.
- Next free ids: FR, AC and ADR numbers are read from the docs when written.

## Review Focus

1. A participant submits an answer shape from another type or a forged id, such as an unknown option, a position out of range, or a list where text is expected: the server refuses or scores zero, and never answers 500 (Tasks 2, 3).
2. Validation fails after files were uploaded in the same form: images stay referenced, and the admin need not choose them again (Task 5).
3. A file with an image extension that is not an image, a decompression bomb, or a corrupt file: refused with a message and no server error (Task 4).
4. A quiz published in one language has an image whose alternative text is filled only in another language after a language is added: publication names the problem (Task 5).
5. "Přepnout" during a run with ticked boxes, pairs and order: answers to unchanged questions come back in every type (Tasks 2, 3).

---

### Task 1: Grading contract and scoring

**Files:**
- Modify: `app/contracts/__init__.py`, `app/plugins/scoring/strategies.py`, `app/plugins/scoring/apps.py`, `app/domain/attempts.py`, `app/domain/authoring.py`, `app/plugins/questions/choice_single/plugin.py`, `tests/fixtures/demo_site/kvz_demo_question/question.py`, `tests/kernel/test_registry.py`, `tests/contracts/question_type.py`, `tests/contracts/test_scoring_basic.py`, `docs/plugin-api.md`
- Test: `tests/contracts/test_scoring_basic.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ItemGrade: right: int; wrong: int; total: int`.
  - `QuestionTypePlugin.grade(self, config: JSON, answer: JSON) -> ItemGrade`.
  - `ScoringStrategyPlugin.evaluate(self, grade: ItemGrade, settings: JSON) -> ScoreBreakdown`, `max_score(self, settings: JSON) -> Decimal`, `supports(self, question_type_id: str) -> bool` (true for every type).
  - `ScoreBreakdown.earned_points: Decimal`, `max_points: Decimal`.
  - Strategy ids `all_or_nothing`, `partial`.

- [ ] **Step 1: Write the failing tests.**

```python
@pytest.mark.parametrize(("right", "wrong", "total", "earned"), [
    (3, 0, 3, "3"), (2, 0, 3, "2"), (2, 1, 3, "1"), (0, 2, 3, "0"), (1, 3, 3, "0"),
])
def test_partial_pays_right_minus_wrong(right, wrong, total, earned):
    grade = ItemGrade(right, wrong, total)
    assert Partial().evaluate(grade, {"points": 3}).earned_points == Decimal(earned)

def test_partial_three_of_three_is_exactly_the_points():
    assert Partial().evaluate(ItemGrade(3, 0, 3), {"points": 1}).earned_points == Decimal(1)

def test_partial_rounds_to_four_places():
    assert Partial().evaluate(ItemGrade(1, 0, 3), {"points": 1}).earned_points == Decimal("0.3333")

@pytest.mark.parametrize(("right", "wrong", "total", "earned"), [(3, 0, 3, "5"), (2, 0, 3, "0"), (3, 1, 3, "0")])
def test_all_or_nothing(right, wrong, total, earned): ...
```
  In `QuestionTypeContract`: `test_grade_of_a_valid_answer_counts_within_total` and `test_grade_of_the_correct_answer_is_complete` using a new class attribute `correct_answer`.

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Partial computes `Fraction(points) * max(0, right - wrong) / total` once, then `Decimal` quantized to 4 places, `ROUND_HALF_UP`. `Attempt.score` keeps three decimals in the column today: change `decimal_places` to 4 on `score`, `max_score` in a migration. Attempts call `plugin.grade` then `strategy.evaluate`; `correct_count` is 1 when complete. `max_score` of a revision sums `strategy.max_score(settings)`.
- [ ] **Step 4: Run all tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: question types grade answers, and strategies only weigh them`.

### Task 2: Výběr

**Files:**
- Create: `app/plugins/questions/choice/` (renamed from `choice_single`, git mv), `tests/contracts/test_choice.py`
- Modify: `pyproject.toml`, `tools/messages.py`, `app/api/rendering.py`, `app/api/play.py`, `app/domain/settings.py`, `app/domain/authoring.py`, `tests/domain/helpers.py` and tests using `choice.single`, `deploy/smoke.sh`
- Delete: `tests/contracts/test_choice_single.py` (its cases move to `test_choice.py`)

**Interfaces:**
- Consumes: `ItemGrade`.
- Produces:
  - Type id `choice`, module id `question.choice`.
  - Definition per the spec. `correct` is a list. `reveal_count` bool, `kind` is `standard` or `yes_no`.
  - Answer, as form strings: `{"options": [ids], "none": "1"}`, keys optional. **Ruling for the spec's `{"none": bool}`:** contract answers arrive as form strings.
  - `play._answers` turns a field whose name ends in `[]` into a list, so inputs are `<id>:options[]` and `<id>:none`.
  - `settings.NONE_OPTION = "none_option"`, `class NoneOption(StrEnum)`: `ALL_QUESTIONS`, `TRICK_QUESTIONS`, default `all_questions`.
  - `question_html` adds `"offer_none": bool` to the payload it gives `render_public`, from the quiz's resolved setting; plugins never read settings.
  - The add menu offers `?type=choice&preset=yes_no`, whose form is prefilled through a new plugin method `initial(preset: str, locales: Sequence[str]) -> JSON` returning translated Ano/Ne. Other types return `{}`; `presets()` lists what the menu shows.

- [ ] **Step 1: Write the failing tests** in `tests/contracts/test_choice.py`, a `QuestionTypeContract` subclass plus:

```python
def test_two_correct_of_three(): grade == ItemGrade(2, 0, 2)
def test_wrong_tick_counts(): options [a, wrong] gives ItemGrade(1, 1, 2)
def test_trick_scores_only_with_none(): correct == [] : {"none": "1"} ItemGrade(1, 0, 1); {} ItemGrade(0, 0, 1); {"options": [a]} ItemGrade(0, 1, 1)
def test_none_on_a_question_with_answers_scores_zero(): {"none": "1"} and with correct ticks: right == 0
def test_nothing_ticked_scores_zero()
def test_unknown_option_is_refused(): validate_submission raises ValueError
def test_answer_of_wrong_shape_is_refused(): {"options": "a"} , {"options": [1]}, {"pair_x": "y"}: ValueError or harmless zero, never another exception
def test_public_payload_has_no_correct_list_and_says_how_many_only_if_revealed()
def test_trick_question_shows_no_hint_even_with_reveal_on()
def test_rendering_uses_checkboxes_for_any_number_of_correct_answers()
def test_none_is_offered_when_payload_says_so(), test_yes_no_never_offers_none()
def test_yes_no_needs_exactly_one_correct()
def test_render_public_keeps_ticks_and_none()   # Review Focus 5
def test_same_text_rule_kept (cases from the existing tests)
```
  In `tests/api/test_play.py`: `test_two_ticks_reach_the_plugin_as_a_list`. In `tests/api/test_public_pages.py`: `test_none_option_all_questions_appears_on_a_standard_question`, `test_none_option_trick_questions_appears_only_on_trick`.

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Move the package. Editor: a checkbox `correct_<row>` per row. `AdminFormError` when `yes_no` has not exactly one correct. Update `helpers.definition` to the new shape; `OPTION_A`, `OPTION_B` stay. Translate "Žádná z odpovědí", "vyberte %(count)s", "Ano", "Ne", in cs, en and uk.
- [ ] **Step 4: Run all tests, `make messages`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: one choice type for one, several or no correct answers, and yes/no`.

### Task 3: Přiřazení

**Files:**
- Create: `app/plugins/questions/matching/`, `app/api/assets/sortable.js`, `tests/contracts/test_matching.py`
- Modify: `pyproject.toml`, `tools/messages.py`, `app/api/public.py`, `app/api/rendering.py`, `app/plugins/theme_default/assets/theme.css`

**Interfaces:**
- Consumes: `ItemGrade`, `_answers` list rule.
- Produces: type id `matching`, module id `question.matching`. Definition per the spec, with `mode`, `direction` of `top_down` or `bottom_up`. Answers as form strings: pairs `{"pair_<item id>": "<item id>"}`, order `{"order": [ids]}` from `<id>:order[]`, without JavaScript `{"pos_<item id>": "<number>"}`. `[data-sortable]` lists in the markup are handled by `sortable.js`.

- [ ] **Step 1: Write the failing tests**, a contract subclass per mode plus:

```python
def test_pairs_grade(): 2 of 3 right gives ItemGrade(2, 0, 3)   # no subtraction
def test_unanswered_pair_is_not_right()
def test_two_rows_choosing_one_text_score_at_most_once()
def test_order_grade_top_down(), test_order_grade_bottom_up_expects_reversed()
def test_no_js_positions_grade_like_the_order_list()
def test_repeated_position_is_refused(), test_position_out_of_range_is_refused()
def test_unknown_item_is_refused()
def test_payload_order_does_not_depend_on_correct_order():
    # same items in another definition order give the same public item order
def test_direction_is_shown_to_the_participant()
def test_render_public_keeps_pairs_and_order()   # Review Focus 5
def test_fewer_than_two_items_cannot_be_published()
def test_two_right_texts_alike_are_refused()
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Items shown sorted by id. `sortable.js`: on load and on `htmx:afterSwap`, turns `[data-sortable]` into a list with a handle and up/down buttons, removes position selects, writes hidden `order[]` inputs in the current order. Pointer events; `touch-action: none` on the handle; no library. Register with `scripts` in `page()`, and in `SERVED_ASSETS`. Rows left blank are dropped as today; a row needs left text and, in pairs, right text.
- [ ] **Step 4: Run all tests, `make messages`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: matching type with pairs and ordering`.

### Task 4: Image storage

**Files:**
- Create: `app/providers/media_local/` (manifest, apps, models with migration, `provider.py`, `views.py`), `tests/providers/test_media_local.py`
- Modify: `app/contracts/__init__.py`, `pyproject.toml`, `uv.lock`, `app/settings.py`, `app/urls.py`, `app/kernel/middleware.py`, `tests/api/test_request_limits.py`, `tests/settings.py`, `tests/support/`, `Dockerfile` if a system library is needed

**Interfaces:**
- Produces:
  - `class ImageRefused(ValueError)` with a translated message.
  - `MediaStorageProvider` protocol: `store_image(name: str, data: bytes) -> str` returning an asset id; `exists(asset_id: str) -> bool`.
  - Port `media_storage` in `PORTS`, registered by `media.local`.
  - URL `/media/<uuid:asset_id>` named `media`.
  - Table `media_asset` per `data-model.md`; `kind` is `image`. Files under `KVZ_MEDIA_PATH`, default `/data/media`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_png_becomes_webp_at_most_1600_px_and_700_kb()
def test_exif_is_gone_from_a_stored_jpeg()
def test_svg_is_stored_unchanged_after_the_basic_check()
def test_gif_above_5_mb_is_refused(), test_raster_above_15_mb_is_refused()
def test_text_named_png_is_refused(), test_corrupt_png_is_refused()
def test_decompression_bomb_is_refused()       # Review Focus 3
def test_heic_is_refused_with_a_helpful_message()
def test_served_with_type_nosniff_and_svg_sandbox()
def test_unknown_asset_is_404()
def test_multipart_allowed_only_on_question_editor_routes()
def test_anonymous_multipart_to_the_editor_gets_no_upload()
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Add Pillow at a pinned version. Set `Image.MAX_IMAGE_PIXELS`. Quality falls step by step, then dimensions, per ADR-0028. SVG basic check: parses as XML with root `svg`, using `xml.etree` limits, and refuses entity declarations. Middleware allows multipart only when the path matches `/admin/quizzes/<uuid>/questions/`. Update its docstring.
- [ ] **Step 4: Run all tests.** Expected: PASS. Also `make smoke`: Pillow must work in the image, and `/data/media` be writable.
- [ ] **Step 5: Commit** `feat: store and serve admin images`.

### Task 5: Images in questions

**Files:**
- Modify: `app/api/admin_quizzes.py`, `app/api/jinja2/admin/question_form.html`, `app/plugins/questions/choice/` (plugin and templates), `tests/contracts/test_choice.py`, `tests/api/test_admin_quizzes.py`

**Interfaces:**
- Consumes: `registry.get("media_storage", ...)`, `store_image`, `ImageRefused`.
- Produces: `<form enctype="multipart/form-data">`. A file input named `image` or `option_<row>_image` is stored by the view, whose id is added to the form data as `<same name>_asset` before `parse_admin`. Definition: `"image": {"asset": id, "alt": {locale: text}}` on the question and on options. Alt inputs `image_alt_<locale>`, `option_<row>_image_alt_<locale>`. A `<name>_remove` checkbox clears an image. `public_payload` has `image: {"url": ..., "alt": ...}`, with the URL built in the API through a callback: `question_html` replaces `asset` by `url`, so plugins never know routes.

- [ ] **Step 1: Write the failing tests.**

```python
def test_upload_with_the_question_stores_and_references_the_image(logged_in)
def test_failed_validation_keeps_the_uploaded_image(logged_in)   # Review Focus 2
def test_refused_file_shows_the_message_and_keeps_other_fields(logged_in)
def test_missing_alternative_text_blocks_publication()           # includes Review Focus 4
def test_option_may_have_only_an_image(), test_option_with_neither_is_dropped()
def test_public_page_shows_image_with_alt_in_the_chosen_language(client)
def test_published_revision_keeps_its_image_after_the_draft_removes_it()
def test_change_of_image_shows_in_the_overview()
def test_same_text_rule_ignores_options_without_text()
def test_hostile_alt_text_is_escaped()
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** `loading="lazy"`, `width: 100%` image rows in `theme.css`. `describe_definition` rows for images and alts.
- [ ] **Step 4: Run all tests, `make messages`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: images in questions and answers`.

### Task 6: Editor and sources

**Files:**
- Create: `app/api/assets/editor.js`, `tests/api/test_question_editor.py`
- Modify: `app/api/admin_quizzes.py`, `admin_forms.py`, `admin_users.py` if the pattern is extracted, `app/api/play.py`, `app/api/rendering.py`, `app/api/jinja.py`, `app/domain/authoring.py`, `app/domain/settings.py`, `app/domain/revision_diff.py`, `app/domain/attempts.py` (percentage), `app/api/jinja2/admin/question_form.html`, `public/_result.html`

**Interfaces:**
- Produces:
  - `authoring.save_question(quiz, question_id, type_id, config, *, points=None, scoring=None, sources=None) -> str`. Question keys `settings.points`, `scoring`, `sources: list[str]`.
  - `settings.SHOW_SOURCES = "show_sources"`, values `on`, `off`, default `on`.
  - `QuestionCommonForm`: `points` 1..100, `scoring` from `available_scoring_strategies`, `sources` textarea checked at 10 lines of 300 characters.
  - Jinja filter `number(value)`: `50` and `12,5` in Czech, `12.5` in English, via `django.utils.formats`.
  - Hidden `form_key` in the question form, consumed once from the session through `admin_quizzes._consume_form_key`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_points_and_scoring_are_saved_and_change_the_maximum(logged_in)
def test_points_outside_1_to_100_are_refused(logged_in)
def test_scoring_not_offered_by_the_type_is_refused(logged_in)
def test_change_of_points_does_not_empty_answers_when_switching()
def test_second_post_with_the_same_form_key_adds_nothing(logged_in)
def test_race_on_slug_shows_the_form_error(logged_in, monkeypatch)
def test_result_lists_sources_with_question_text_when_on(client)
def test_result_hides_sources_when_off(client)
def test_only_https_line_becomes_a_link(client), test_markup_in_a_source_is_escaped(client)
def test_sources_change_shows_in_the_overview(logged_in)
def test_more_than_ten_sources_are_refused(logged_in)
def test_percentage_is_written_for_the_language(client):
    # 50 %, 12,5 % in cs, 12.5 % in en, never 50.0 %
```

- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** `editor.js` (loaded only on admin pages): warns through `beforeunload` when a `form.watch-changes` differs from its initial state, disables a submit button after the first click, and unticks other options when "Žádná" is ticked in public forms, so that one is loaded everywhere and checks what is on the page. Add `watch-changes` to the question and settings forms. Replace `percentage_display` use with the filter. Close TD-010 with `make tech-debt-resolve id=TD-010`.
- [ ] **Step 4: Run all tests, `make messages`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: full question editor, sources on the result and TD-010`.

### Task 7: Documents and full verification

**Files:**
- Create: new ADR for the merged types and `grade`, in `docs/_architecture/adr/`
- Modify: `docs/_architecture/roadmap.md`, `plugins/question-types.md`, `plugins/scoring.md`, `providers/media-local.md`, `data-model.md`, `modules/api-ui.md`, `modules/contracts.md`, `modules/kernel.md`, `security.md`, `acceptance-criteria.md`, `README.md`, `docs/plugin-api.md`, `docs/deployment.md`, `THIRD_PARTY.md`, `CLAUDE.md`, `app/plugins/CLAUDE.md`, `app/providers/CLAUDE.md`, `app/api/CLAUDE.md`, `tests/CLAUDE.md`, `deploy/smoke.sh`

- [ ] **Step 1: Update docs.** Roadmap: B2 row as built, B4 keeps external addresses, new B6 with numeric, text fill-in, image upload by participant, `FR-46`; AC-16 and AC-17 stage notes; a note in C on sources in competitions. New `FR` for sources in `question-types.md` plus the `README.md` map. New `AC` for types, images and sources. Settings table in `api-ui.md` gains the new rows. `security.md`: multipart exception, SVG headers. `THIRD_PARTY.md`: Pillow.
- [ ] **Step 2: Extend `deploy/smoke.sh`:** create a question with an image through the service, confirm its `/media/<id>` answers 200 with `image/webp`, and that a multipart POST to `/` answers 415.
- [ ] **Step 3: Run the checks.** Dev container: ruff, mypy, pytest, gitleaks, `tech-debt-check`. Host: `make smoke`. Expected: all pass.
- [ ] **Step 4: Browser walkthrough** on the Compose stack at 360 and 1280 px, light and dark: write the user's quiz question with 3 correct answers in three languages; a trick question; yes/no; pairs; order in both directions by mouse, touch, keyboard and without JavaScript; images in question and answers, including a real phone photo size; result with sources on and off; leaving a changed form; publishing during a run and "Přepnout" keeping answers. No console errors, no horizontal page scroll. Send screenshots to the user.
- [ ] **Step 5: Commit** `docs: record question types, images and sources`.

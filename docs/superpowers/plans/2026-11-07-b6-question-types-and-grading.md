# B6 Question types, grading and answer visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add types Číslo, Text and Fotka, grading of photos, chosen storage and visibility of answers, a private result link, a public walkthrough, and working module requirements.

**Architecture:** Three plugins behind `QuestionTypePlugin`, extended with `file_fields`, `needs_grading` and `summarize`. A new `attempt_answer` table and `app/domain/grading.py` hold what a person judges; the score recalculates there. Requirements are declared in manifests and checked by `app/domain/requirements.py`. Photos are private assets of the media provider, served only through routes that check the right.

**Tech Stack:** Python 3.15, Django 6.1, Jinja2, HTMX, SQLite, Pillow. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-07-b6-question-types-and-grading-design.md`

## Global Constraints

- Branch `feat/b6-question-types-and-grading` from `main`. Nothing pushed; no remote.
- Every user-facing string goes through `gettext`. Public pages in cs, en, uk; `admin*` in cs, en (`app/api/CLAUDE.md`). `QuizRun` is běh/run; never kolo. Texts are not in the first person.
- Settings rule (ADR-0042): every new setting declares scopes; a narrower scope has a reason. Number and text state `settings: []`.
- Layers: `app/domain` imports no `app/api`, `app/plugins`, `app/providers`; `app/kernel` imports no domain or API; plugins read no settings.
- Tests never use the network and use small generated images.
- `kvizotron-browser` data is kept. Smoke: `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke`. A changed Caddyfile needs `up -d --force-recreate caddy`.
- Limits (ADR-0028): PNG, JPEG, WebP; 15 MB; stored as WebP, longest side 1600 px, at most 700 KB; 2 GB per run. Text: up to 10 blanks. Module ids: `question.number`, `question.text`, `question.image_answer`; type ids `number`, `text`, `image_answer`.
- Commits end with the attribution lines the session gives.

## Review Focus

Each has its test in the owning task.

1. A forged form field `<question id>:image=<some asset id>` without a file: ignored, no points, no reach to another's asset (Task 5).
2. A portrait phone photo with EXIF orientation: stored upright, EXIF gone (Task 5).
3. `PENDING_GRADING` meeting code that knows only `SUBMITTED`: resubmit, switch, revision polling, run counts (Task 4).
4. Double submit with a file: one result, the loser's file removed (Task 5).
5. Text prompt with HTML around a marker, a `{{`, or a marker missing in one language: escaped, literal, and a publication problem (Task 2).

---

### Task 1: Type number

**Files:**
- Create: `app/plugins/questions/number/{__init__,apps,manifest,plugin}.py`, `jinja2/number/{admin,public,solution}.html`, `locale/`
- Modify: `pyproject.toml` (entry point `"question.number"`), `tools/messages.py` (`ROOTS`), `tests/test_layers.py` if it lists modules
- Test: `tests/contracts/test_number.py`

**Interfaces:**
- Produces: `NumberQuestion`, id `number`. Definition: `{"prompt": {locale: text}, "image": optional, "value": "3.14", "tolerance": "5", "tolerance_kind": "none" | "absolute" | "percent"}`. Answer: `{"value": "3,14"}`. `grade` returns `ItemGrade(1, 0, 1)` or `ItemGrade(0, 1, 1)`. `available_scoring_strategies() == ["all_or_nothing"]`. Module-level `parse_number(text: str) -> Decimal` raising `ValueError`.
- CSV columns: `prompt_<l>`, `correct_value`, `tolerance`, `tolerance_kind`, `image`, `image_alt_<l>`.

- [ ] **Step 1: Write failing tests:** subclass `QuestionTypeContract` as `tests/contracts/test_matching.py` does, plus:

```python
@pytest.mark.parametrize("text,value", [("3,14", "3.14"), ("3.14", "3.14"), ("-2", "-2"), (" 7 ", "7")])
def test_reads_comma_and_dot(text, value): assert parse_number(text) == Decimal(value)
@pytest.mark.parametrize("text", ["1,000.5", "1.2.3", "1e5", "NaN", "Infinity", "", "١٢", "1 000"])
def test_refuses(text): ...                         # ValueError
@pytest.mark.parametrize("answer,right", [("950", True), ("1050", True), ("949.99", False), ("1050,01", False)])
def test_percent_tolerance_is_inclusive(answer, right): ...   # 1000 ±5 %
def test_percent_uses_the_absolute_value(): ...     # -100 ±10 % accepts -110 and -90
def test_absolute_tolerance(): ...
def test_exact_decimals_not_floats(): ...           # 0.1 ±0.2 accepts 0.3
def test_percent_on_zero_is_refused_by_the_editor(): ...     # AdminFormError from parse_admin
def test_public_payload_holds_no_value_or_tolerance(): ...
def test_input_allows_only_number_characters(): ... # inputmode="decimal", a pattern attribute
def test_solution_shows_value_and_tolerance(): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/contracts/test_number.py -q`. Expected: FAIL on import.
- [ ] **Step 3: Implement** per `app/plugins/questions/matching/` layout. `parse_number` uses `re.fullmatch(r"-?\d+([.,]\d+)?", text.strip(), re.ASCII)`, at most 30 digits. `validate_submission` raises `ValueError` for unreadable non-blank text; a blank value is no answer.
- [ ] **Step 4: Run:** `make messages`, then the test and `tests/test_translations.py tests/contracts/test_settings_rule.py`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat: question type number`

### Task 2: Type text

**Files:**
- Create: `app/plugins/questions/text/{__init__,apps,manifest,plugin}.py`, `jinja2/text/{admin,public,solution}.html`, `locale/`
- Modify: `pyproject.toml`, `tools/messages.py`
- Test: `tests/contracts/test_text.py`

**Interfaces:**
- Produces: `TextQuestion`, id `text`. Definition: `{"prompt": {locale: text}, "image": optional, "blanks": [{"id": hex, "accepted": {locale: [text]}}], "ignore_case": true, "ignore_spaces": true, "ignore_diacritics": false}`. A prompt with no markers has exactly one blank. Answer: `{"blank_1": text, ...}`. `grade`: `right` blanks matched, `wrong` 0, `total` blanks. Strategies `["all_or_nothing", "partial"]`. Module-level `normalized(text: str, *, ignore_case: bool, ignore_spaces: bool, ignore_diacritics: bool) -> str`.
- CSV columns: `prompt_<l>`, `answer_<N>_<l>` (one per line), `ignore_case`, `ignore_spaces`, `ignore_diacritics`, `image`, `image_alt_<l>`.

- [ ] **Step 1: Write failing tests:** contract subclass, plus:

```python
def test_defaults_ignore_case_and_spaces_not_diacritics(): ...   # " PLZEŇ " right, "Plzen" wrong
def test_ignoring_diacritics_changes_only_latin():
    n = partial(normalized, ignore_case=False, ignore_spaces=False, ignore_diacritics=True)
    assert n("Plzeň") == n("Plzen")
    assert n("и") != n("й")
    assert n("ї") != n("і")
def test_nfc_and_nfd_compare_equal(): ...
def test_accepted_answers_of_any_language_count(): ...
def test_blanks_score_separately_with_partial(): ...      # 1 of 2 → right=1, total=2, wrong=0
def test_markers_in_any_order_per_language(): ...         # cs "{1} a {2}", en "{2} and {1}"
def test_no_marker_means_one_field_under_the_prompt(): ...
def test_marker_missing_in_one_language_fails_validation(): ...   # ValueError from validate_definition
def test_more_than_ten_blanks_refused(): ...
def test_double_brace_is_a_literal_brace(): ...
def test_html_around_a_marker_is_escaped(): ...           # "<b>{1}</b>" renders &lt;b&gt; and one input
def test_each_input_has_a_label_naming_its_blank(): ...
def test_accepted_answers_never_in_the_public_payload(): ...
def test_solution_lists_accepted_answers_of_the_locale(): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/contracts/test_text.py -q`. Expected: FAIL on import.
- [ ] **Step 3: Implement.** Diacritics: NFD, drop a combining mark (`unicodedata.combining`) only when the preceding base character's `unicodedata.name` starts with `LATIN`, then NFC. Prompt rendering splits on `\{\{|\{\d+\}`, escaping every piece, so `Markup` is built only from escaped text and inputs.
- [ ] **Step 4: Run:** `make messages`, then the test, `tests/test_translations.py`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat: question type text`

### Task 3: Module requirements

**Files:**
- Create: `app/domain/requirements.py`
- Modify: `app/kernel/manifest.py`, `app/kernel/registry.py`, `app/domain/settings.py`, `app/domain/authoring.py`, `app/api/admin_quizzes.py`, `app/api/admin_workspace.py`, `app/api/admin_urls.py`, `app/api/jinja2/admin/_quiz_header.html`, `question_form.html`, catalogues
- Test: `tests/domain/test_requirements.py`, `tests/kernel/test_manifest.py`, `tests/api/test_requirements.py`

**Interfaces:**
- Produces, in manifest: `settings_requirements: dict[str, SettingRequirement]`, with `SettingRequirement(refuse: list[str], use: str, reason: str)`, `use` not among `refuse`. A requirement with an unknown key, or a value not offered, raises `StartupError` from `settings.register_modules`.
- Produces, in registry: `owner_of(capability: str, key: str) -> str`.
- Produces, in `requirements`:
  - `Requirement(module: str, key: str, refuse: tuple[str, ...], use: str, reason: str)`
  - `of_quiz(quiz) -> list[Requirement]`: modules of types used in the draft (or the published content) and draw pools
  - `of_type(type_id: str) -> list[Requirement]`
  - `unmet(quiz, requirements=None) -> list[Requirement]`
  - `contradiction(requirements) -> tuple[Requirement, Requirement] | None`: same key, each's `use` refused by the other
- Produces, in `authoring`: `validate_for_publication` adds `Problem(None, None, "requirement", reason)` and `"requirement_conflict"`; `open_run` raises new `RequirementUnmet(reasons: list[str])`.
- Route `quizzes/<uuid>/requirements/use`, POST field `key`, name `admin_requirement_use`: sets the quiz override to `use`, audited through `set_override`.

- [ ] **Step 1: Write failing tests:** a helper patches `django_settings.KVZ_MODULES` with a manifest requiring `reveal_moment` refuse `["after_each"]`, use `"at_end"`, for the module owning `choice`:

```python
def test_manifest_requires_a_use_outside_refuse(): ...
def test_unknown_key_or_value_is_a_startup_error(): ...
def test_unmet_blocks_publication_with_the_reason(): ...
def test_met_allows_publication(): ...
def test_unmet_blocks_opening_a_run(): ...
def test_type_only_in_a_draw_pool_counts(): ...
def test_type_not_used_requires_nothing(): ...
def test_contradicting_requirements_block(): ...
def test_requirement_is_read_through_resolve(): ...     # a global value counts, a quiz override beats it
def test_editor_shows_requirement_and_use_button(logged_in): ...
def test_use_sets_the_override_and_is_audited(logged_in): ...
def test_use_refuses_an_unknown_key(logged_in): ...
def test_publish_page_lists_the_reason(logged_in): ...
def test_run_open_shows_the_reason(logged_in): ...
def test_test_link_draft_copy_is_blocked(): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/domain/test_requirements.py tests/api/test_requirements.py tests/kernel/test_manifest.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Reasons are msgids resolved through the module's catalogue, like setting labels. `workspace()` adds `requirements` (unmet) shown in the header; `question_form` shows `of_type` for that type, when in a quiz. The bank editor shows none.
- [ ] **Step 4: Run:** `make messages`, then `uv run pytest tests/domain tests/api tests/kernel -q`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat: module requirements on settings`

### Task 4: Stored answers and pending attempts

**Files:**
- Create: `app/domain/grading.py`, a migration
- Modify: `app/domain/models.py`, `app/domain/settings.py`, `app/domain/attempts.py`, `app/domain/reveal.py`, `app/domain/run_links.py`, `app/contracts/__init__.py`, all question plugins and `tests/fixtures/demo_site/kvz_demo_question/question.py`, `tests/kernel/test_registry.py` (stub), `tests/contracts/question_type.py`, `app/api/admin_forms.py`, `app/api/admin_runs.py`, `app/api/play.py`
- Test: `tests/domain/test_grading.py`, `tests/domain/test_stored_answers.py`

**Interfaces:**
- Produces, in contracts: `QuestionTypePlugin.file_fields(config: JSON) -> Sequence[str]`, `needs_grading(config: JSON, answer: JSON | None) -> bool`. Existing types return `[]` and `False`.
- Produces, in models: `Attempt.Status.PENDING_GRADING`, `Attempt.FINISHED = (SUBMITTED, PENDING_GRADING)`. `AttemptAnswer` (db table `attempt_answer`): `id`, `attempt` FK, `question_id`, `answer_json`, `auto_points`, `manual_max`, `manual_points` null, `graded_by`, `graded_at`, `asset_id` null, `removed`, `approved`; unique `(attempt, question_id)`. `HiddenAnswerValue` (`hidden_answer_value`): `run` FK, `question_id`, `value_key`, `hidden_by`, `created_at`.
- Produces, in settings: `STORE_ANSWERS` (`images`, `all`), `ANSWERS_VISIBILITY` (`admins`, `participant`, `public`), `GRADING_VIEW` (`by_question`, `by_attempt`), each with `QUIZ_WIDE` scopes and a reason; `answers_visibility(quiz) -> str`: `admins` when the combination conflicts; `is_visibility_conflict(store: str, visibility: str) -> bool`.
- Produces, in `attempts`: `settings_json["store_answers"]` frozen at start; `submit` writes `AttemptAnswer` rows in the `_store` transaction and sets the pending status.
- Produces, in `grading`:
  - `waiting(run) -> int`
  - `save_manual(answer: AttemptAnswer, points: Decimal, *, admin_id: str) -> None`, raising `InvalidPoints`
  - `remove_photo(answer: AttemptAnswer, *, admin_id: str) -> str | None`: returns the asset id for the API to delete
  - `set_approved(answer, approved: bool, *, admin_id: str) -> None`
  - `recalculated(attempt) -> None`: score is the submitted automatic points plus manual points; leaves pending when no row waits
- `run_links.delete` and `delete_attempts` return `list[str]` of asset ids, and delete answer rows.

- [ ] **Step 1: Write failing tests:**

```python
def test_default_stores_nothing_for_types_without_a_file(): ...
def test_store_all_stores_each_answered_question_with_its_points(): ...
def test_blank_answers_are_not_stored(): ...
def test_setting_is_frozen_at_start(): ...               # changed after start, the attempt keeps it
def test_replaced_attempt_keeps_no_rows(): ...
def test_needs_grading_gives_pending_and_automatic_score(): ...  # fake type: 2 of 10
def test_no_image_is_submitted_not_pending(): ...
def test_save_manual_recalculates_and_leaves_pending_when_none_waits(): ...
def test_two_photos_stay_pending_until_both_are_graded(): ...
def test_points_outside_zero_to_max_refused(): ...
def test_regrading_after_the_run_ended(): ...
def test_every_change_is_audited_without_content(): ...
def test_remove_photo_sets_zero_keeps_automatic_and_returns_asset(): ...
def test_decimal_points_stay_exact(): ...                # 1.65 + 3.35 = 5
# Review Focus 3
def test_resubmit_of_a_pending_attempt_returns_its_result(): ...
def test_switch_of_a_pending_attempt_is_already_submitted(): ...
def test_revision_polling_stops_for_a_pending_attempt(client): ...
def test_run_counts_include_pending(logged_in): ...
def test_quiz_form_refuses_public_without_all(logged_in): ...
def test_global_conflict_behaves_as_admins_and_warns(logged_in): ...
def test_defaults_change_nothing_for_an_existing_quiz(client): ...
def test_shared_contract_new_methods(): ...              # QuestionTypeContract: file_fields, needs_grading
```

- [ ] **Step 2: Run:** `uv run pytest tests/domain/test_grading.py tests/domain/test_stored_answers.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Grep every `Status.SUBMITTED` and use `Attempt.FINISHED` where a finished attempt is meant. `reveal.State.PENDING` with text `_("Waiting for grading")` for a question whose `needs_grading` holds; earned shows the automatic part. Remember `tests/contracts/test_demo_question.py` counts tests.
- [ ] **Step 4: Run:** `make messages`, then `uv run pytest tests/domain tests/api tests/contracts tests/kernel -q`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat: stored answers and attempts waiting for grading`

### Task 5: Type image answer and private photos

**Files:**
- Create: `app/plugins/questions/image_answer/{__init__,apps,manifest,plugin}.py`, `jinja2/image_answer/{admin,public,solution}.html`, `locale/`, media migration
- Modify: `pyproject.toml`, `tools/messages.py`, `app/contracts/__init__.py`, `app/providers/media_local/{models,provider}.py`, `app/api/public.py`, `app/api/play.py`, `app/api/admin_preview.py`, `app/api/apps.py`, `app/kernel/middleware.py`, `app/api/jinja2/public/_questions.html`, `app/api/jinja2/admin/question_form.html` and the bank's editor (a class telling quiz from bank), CSS
- Test: `tests/contracts/test_image_answer.py`, `tests/providers/test_media_participant.py`, `tests/api/test_image_answer.py`

**Interfaces:**
- Consumes: Task 3 requirements, Task 4 contract and rows.
- Produces, in contracts: `PHOTO_VISIBILITY = "photo_visibility"`; `StoredImage.private: bool = False`; `MediaStorageProvider.store_participant_image(data: bytes, *, run_assets: Sequence[str]) -> str` (raises `ImageRefused`), `check_participant_image(data: bytes) -> None`, `delete_image(asset_id: str) -> None`.
- Produces: `ImageAnswerQuestion`, id `image_answer`. Definition: `{"prompt", "image": optional, "auto": {"right": 2, "total": 10}}`. Answer: `{"image": asset_id}`. `grade` returns `ItemGrade(auto.right, 0, auto.total)` with an image, else `ItemGrade(0, 0, auto.total)`. `file_fields -> ["image"]`. `needs_grading` true with an image. `available_scoring_strategies() == ["partial"]`. `question_settings() == [PHOTO_VISIBILITY]`.
- Manifest: setting `photo_visibility` (`author` default, `admins`, `public`), all scopes; `settings_requirements`: `reveal_moment` refuse `["after_each"]`, use `at_end`.
- `parse_admin`: `points` in the form means a quiz, so `auto = {auto_points, points}`, refusing automatic above total; otherwise `auto_percent`, whole, gives `{n, 100}`.
- CSV: `prompt_<l>`, `auto_points`, `auto_share` (percent), `image`, `image_alt_<l>`.
- Produces, in kernel middleware: `public_upload_check: Callable[[HttpRequest], bool] | None`, set in `app.api` `ready()`: true for `/a/<id>/submit` when the attempt is in progress, its run open, and it holds a type with `file_fields`. No body is read.
- Produces, in `play.py`: `_with_files(request, attempt, answers) -> list[str]`: first removes any form value for a file field, then stores each file; returns stored asset ids; raises `ImageRefused`.

- [ ] **Step 1: Write failing tests:**

```python
# Provider
def test_portrait_exif_is_stored_upright_and_exif_is_gone(): ...   # Review Focus 2
def test_disguised_file_refused(): ...                  # a script named .jpg
@pytest.mark.parametrize("fmt", ["GIF", "SVG"])
def test_only_png_jpeg_webp(fmt): ...
def test_15_mb_limit_and_stored_at_most_700_kb(): ...
def test_pixel_limit(): ...
def test_run_limit_refuses_the_next(monkeypatch): ...   # limit patched small
def test_delete_removes_row_and_file(): ...
# Contract and editor
def test_two_of_ten_pays_two_through_partial(): ...
def test_automatic_above_total_refused(): ...
def test_zero_automatic_is_allowed(): ...
def test_row_of_five_at_twenty_percent_gives_one(): ...  # AC-55, through a draw row
def test_row_of_five_at_33_percent_gives_1_65(): ...
def test_bank_editor_asks_percent_and_quiz_editor_points(logged_in): ...
# Upload
def test_public_media_answers_404_for_a_participant_photo(client): ...
def test_multipart_refused_on_submit_of_an_attempt_without_this_type(client): ...
def test_multipart_refused_when_the_attempt_is_finished(client): ...
def test_multipart_form_has_encoding_only_when_needed(client): ...  # hx-encoding, enctype
def test_submit_with_photo_shows_two_of_ten_pending(client): ...    # AC-55
def test_submit_without_photo_is_zero_and_nothing_waits(client): ...
def test_refused_file_keeps_other_answers_without_script(client): ...
def test_forged_image_field_is_ignored(client): ...      # Review Focus 1
def test_double_submit_one_result_loser_file_removed(client): ...   # Review Focus 4
def test_failed_submit_removes_the_stored_file(client): ...
def test_preview_reads_the_file_and_stores_nothing(logged_in): ...
def test_test_link_delete_removes_its_photos(logged_in): ...
def test_public_level_warns_before_upload(client): ...
def test_after_each_requirement_is_real(logged_in): ...  # AC-61
def test_reveal_at_end_says_waiting(client): ...
def test_csv_round_trip_keeps_the_split(logged_in): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/contracts/test_image_answer.py tests/providers/test_media_participant.py tests/api/test_image_answer.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Rebuild: `ImageOps.exif_transpose` first, then new pixels through the existing `_to_webp`, without passing `exif`. `public.media` returns 404 when `stored.private`. The file reads before the attempt transaction; if `submit` raises, or returns a stored result, delete what was stored. Run total comes from answer rows' asset ids.
- [ ] **Step 4: Run:** `make messages`, then `uv run pytest tests/api tests/providers tests/contracts tests/domain tests/test_translations.py tests/contracts/test_settings_rule.py tests/test_layers.py -q`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat: question type image answer with private photos`

### Task 6: Grading pages

**Files:**
- Create: `app/api/admin_grading.py`, `app/api/jinja2/admin/grading.html`, `_grading_photo.html`
- Modify: `app/api/admin_urls.py`, `_quiz_header.html`, `app/api/admin_links.py`, `test_links.html`, `admin_workspace.py`, CSS, catalogues
- Test: `tests/api/test_grading.py`

**Interfaces:**
- Consumes: `grading.*`, `settings.GRADING_VIEW`, `delete_image`.
- Produces: tab key `grading`, label `_("Grading")`, routes `quizzes/<uuid>/grading` (`?run=<id>&question=<id>&page=<n>`, name `admin_quiz_grading`), `answers/<uuid>/points` (POST), `answers/<uuid>/delete` (GET confirms, POST deletes), `answers/<uuid>/approve` (POST), `answers/<uuid>/photo` (GET, admins, `Cache-Control: private, no-store`).

- [ ] **Step 1: Write failing tests:**

```python
def test_tab_shows_the_number_waiting_without_test_attempts(logged_in): ...
def test_by_question_gallery_shows_photos_and_fields(logged_in): ...
def test_by_attempt_shows_all_stored_answers_and_grades_only_photos(logged_in): ...
def test_setting_chooses_the_view(logged_in): ...
def test_running_run_comes_first(logged_in): ...
def test_points_save_with_htmx_and_without(logged_in): ...
def test_invalid_points_show_a_message_and_keep_the_value(logged_in): ...
def test_delete_asks_first_and_removes_the_file(logged_in): ...    # AC-56
def test_approve_only_offered_at_public_level(logged_in): ...
def test_test_link_has_a_grade_action_for_its_run(logged_in): ...
def test_run_of_another_quiz_is_404(logged_in): ...
def test_login_required_everywhere_and_photo_no_store(client, logged_in): ...
def test_fields_have_labels(logged_in): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/api/test_grading.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** 20 attempts per page in the by-attempt view, 30 photos per page in the gallery, `loading="lazy"`. HTMX swaps one photo's fragment; without it, the post redirects back keeping `run`, `question` and `page`. Add the new route arguments to `ARGUMENTS` in `tests/api/test_request_limits.py`.
- [ ] **Step 4: Run:** `make messages`, then `uv run pytest tests/api tests/test_translations.py -q`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat: grading by question or by attempt`

### Task 7: Private result link and the same device

**Files:**
- Create: `app/domain/visibility.py`, `app/api/jinja2/public/result.html`, `_result_answers.html`
- Modify: `app/domain/tokens.py`, `app/api/public.py`, `app/urls.py`, `app/api/play.py`, `app/api/jinja2/public/_result.html`, `quiz.html`, `app/api/assets/play.js`, privacy page, catalogues
- Test: `tests/api/test_result_link.py`, `tests/domain/test_visibility.py`

**Interfaces:**
- Produces, in `tokens`: `issue_result(attempt_id: UUID) -> str`, `verify_result(token: str) -> UUID`, salt `kvizotron.result`.
- Produces, in `visibility`: `photo_level(quiz, question) -> str`, `author_sees_photo(answer, quiz, question) -> bool`, `public_sees_photo(answer, quiz, question) -> bool` (needs level `public`, approval, not removed, run ended, normal run), `participant_sees_answers(attempt) -> bool`, `has_more_to_see(attempt) -> bool`.
- Produces: `/v/<str:token>` (`result`), `/v/<str:token>/photo/<uuid>` (`result_photo`). An invalid token gives 200 and one message; a refused photo gives 204, as a 4xx would log the path.

- [ ] **Step 1: Write failing tests:**

```python
def test_link_shown_when_waiting_or_more_to_see_only(client): ...
def test_link_shows_provisional_then_final_score(client, logged_in): ...  # AC-58
def test_own_answers_only_at_participant_or_public(client): ...
def test_own_photo_at_author_not_at_admins(client): ...
def test_no_correct_answer_unless_reveal_allows(client): ...
def test_deleted_photo_is_gone_from_the_link(client, logged_in): ...
def test_deleted_test_link_ends_it(client): ...
def test_invalid_token_is_200_with_one_message_and_never_logged(client, caplog): ...
def test_noindex_and_no_referrer_and_no_store_on_photo(client): ...
def test_test_attempt_says_it_is_a_test(client): ...
def test_quiz_page_has_a_slot_and_result_a_link_for_the_script(client): ...
def test_privacy_page_mentions_photos_and_the_stored_link(client): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/api/test_result_link.py tests/domain/test_visibility.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** `play.js` stores `kvz-result-<slug>` from a `data-result-link` attribute, in `try`/`catch`, and fills a hidden `data-result-slot` on the quiz page.
- [ ] **Step 4: Run:** `make messages`, then `uv run pytest tests/api tests/domain tests/test_translations.py -q`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat: private result link, remembered on the same device`

### Task 8: Public walkthrough

**Files:**
- Create: `app/domain/walkthrough.py`, `app/api/jinja2/public/walkthrough.html`
- Modify: `app/contracts/__init__.py`, all question plugins and the demo, `tests/contracts/question_type.py`, `tests/kernel/test_registry.py`, `app/api/public.py`, `app/urls.py`, `app/api/admin_runs.py`, `run.html`, `quiz.html`, `app/domain/settings.py` (help line), catalogues
- Test: `tests/api/test_walkthrough.py`

**Interfaces:**
- Consumes: `visibility.public_sees_photo`, `HiddenAnswerValue`, stored answers.
- Produces, in contracts: `AnswerCount(key: str, label: str, count: int)`; `QuestionTypePlugin.summarize(config: JSON, answers: Sequence[JSON], locale: str) -> Sequence[AnswerCount]`. Most frequent first; image answer returns `[]`.
- Produces, in `walkthrough`: `available(run) -> bool`, `shows_answers(run) -> bool`, `of_run(run, locale) -> list[WalkthroughQuestion]`, `hide_value(run, question_id, key, *, admin_id)`, `show_value(...)`.
- Routes: `q/<slug>/r/<uuid>/answers` (`walkthrough`), `q/<slug>/r/<uuid>/photo/<uuid>` (`walkthrough_photo`), admin `runs/<uuid>/answers/hide` (POST).

- [ ] **Step 1: Write failing tests:**

```python
def test_unavailable_during_an_open_run_and_when_not_public(client): ...   # one plain message
def test_counts_without_a_link_to_a_participant(client): ...               # Praha 2×, Brno 1×
def test_text_is_counted_after_the_questions_comparison(client): ...       # "praha" and "PRAHA" together
def test_test_attempts_never_appear(client): ...
def test_hidden_value_is_gone_and_audited(client, logged_in): ...
def test_admin_sees_hide_action_public_does_not(client, logged_in): ...
def test_public_photos_alone_show_prompt_and_approved_photos_no_answers(client): ...  # AC-60
def test_unapproved_photo_is_204_and_absent(client): ...
def test_photo_refused_during_open_run(client): ...
def test_newer_revision_shows_its_questions_and_drops_old_answers(client): ...
def test_contract_summarize_counts_and_holds_no_html(self): ...            # shared suite
def test_settings_page_warns_about_free_text(logged_in): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/api/test_walkthrough.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Solutions through `render_solution`, as elsewhere. Text keys are the compared form, labels the most frequent original. Run with attempts on several revisions uses `run.current_revision` for the question list.
- [ ] **Step 4: Run:** `make messages`, then `uv run pytest tests/api tests/contracts tests/test_translations.py -q`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat: public walkthrough of a finished run`

### Task 9: Documents and verification

**Files:**
- Create: `docs/_architecture/adr/0046-stored-answers-and-who-sees-them.md`, `0047-image-answer-photo-visibility.md`
- Modify: `docs/_architecture/adr/README.md`, `0033-...md` (status line pointing to ADR-0047), `acceptance-criteria.md` (AC-16 split, AC-17, AC-53 to AC-61), `roadmap.md` (B6 done, C4 narrowed), `plugins/question-types.md`, `plugins/scoring.md`, `modules/kernel.md`, `modules/domain.md`, `modules/contracts.md`, `data-model.md`, `security.md`, `docs/privacy.md`, `docs/plugin-api.md`, `app/providers/csv_io/sample/csv-format.md`, `tests/providers/test_csv_sample.py`, `CLAUDE.md`, `app/domain/CLAUDE.md`, `app/api/CLAUDE.md`, `app/plugins/CLAUDE.md`, `app/providers/CLAUDE.md`

- [ ] **Step 1: Write the documents.** ADR-0046 covers storage, the three levels, the link and the walkthrough. ADR-0047 supersedes ADR-0033's "never public", adds grading in Stage B and the share carried by `ItemGrade`. `csv-format.md` and its test gain all new columns. Privacy states: photos and answers when stored, who sees them, the link in `localStorage`, and that photos stay until deleted, until D3.
- [ ] **Step 2: Run:** `make quality`. Expected: lint, tests, gitleaks and the tech-debt check pass.
- [ ] **Step 3: Run smoke:** `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke`. Expected: all PASS.
- [ ] **Step 4: Verify in a browser on a rebuilt `kvizotron-browser`, on a new quiz:** number and text on a phone, including blanks in three languages; a photo with and without a script, through Caddy at over 10 MB; grading in both views; link and same-device return; walkthrough on a projector-width and a phone; keyboard through inputs, file field and gallery; dark mode.
- [ ] **Step 5: Commit:** `docs: milestone B6, question types, grading and answer visibility`

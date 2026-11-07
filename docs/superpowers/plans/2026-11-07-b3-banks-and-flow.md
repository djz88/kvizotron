# B3 Banks and flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quizzes that mix own questions with draws from shared banks, shuffle, walk through in three navigation modes with progress, and reveal answers and explanations after each question or at the end.

**Architecture:** An attempt freezes at start which questions it got (`selection_json`) and how it behaves (`settings_json`); everything after start reads those, never the whole revision or the live settings. Draw rows live in the draft next to `questions`; publication copies each row's usable questions into the revision as its pool. One form holds all selected questions and is submitted once; `flow.js` shows them one at a time, and `POST /a/<id>/check` returns a reveal fragment and stores nothing.

**Tech Stack:** Django 6.1, Jinja2, HTMX, Pico CSS, SQLite. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-07-b3-banks-and-flow-design.md`

## Global Constraints

- Branch `feat/b3-banks-and-flow`. Tests run in the dev container, because host uv is older than 0.13: `make test`, `make lint`, `make quality`, `make messages`.
- Plugins import only `app.contracts`; `domain` imports no `api`, `plugins` or `providers` (`tests/test_layers.py`). No inline scripts or styles (CSP).
- Every quiz can be completed without JavaScript. Every control works by keyboard, at 360 px and on desktop.
- Admin strings in cs and en, public strings in cs, en and uk. In Czech a `QuizRun` is běh, never kolo.
- `public_payload()` and `render_public()` never contain a correct answer or an explanation.
- Nothing stores a participant's answers. Audit and logs contain no answers.
- Defaults leave an existing quiz as it is: `all_at_once`, `never`, `verdict`, `off`, `off`.
- Limits **[plan's call]**: draw count and points per question 1 to 100; explanation up to 2000 characters per language; a tag up to 40 characters, at most 10 tags per question; bank name up to 120 characters.
- `kvizotron-browser` stack keeps its data; verification there adds a new quiz. Its in-progress attempts have no selection (Review Focus 1).

## Review Focus

1. An attempt already in progress at the upgrade, with empty `selection_json` and `settings_json`: it submits, switches and scores as before, all questions in revision order (Task 1).
2. One bank question in two rows with different points: it is scored with the points of the row that drew it (Task 8).
3. A locked answer after Zkontrolovat: it is still in the final submission, because a disabled input would not be sent (Task 6, checked in the browser in Task 9).
4. A pairs question left with every select on the placeholder: the reveal says Bez odpovědi, not Špatně (Task 5).
5. A language added to a quiz after publication, and a quiz with draw rows and no own question: the usable count falls and publication says so when too few remain; the second one publishes and does not report "no questions" (Task 7).

---

### Task 1: Flow settings frozen on the attempt

**Files:**
- Create: `app/domain/selection.py`, `app/domain/migrations/0007_attempt_selection_settings.py`, `tests/domain/test_selection.py`, `tests/domain/test_flow_settings.py`
- Modify: `app/domain/settings.py`, `app/domain/models.py`, `app/domain/attempts.py`, `app/api/admin_forms.py`, `app/api/admin_quizzes.py`, `app/api/jinja2/admin/quiz_settings.html`, `app/api/play.py`, `app/api/rendering.py`, `tests/domain/test_attempts.py`, `tests/api/test_admin_settings.py`

**Interfaces:**
- Produces:
  - `settings.NAVIGATION_MODE`, `REVEAL_MOMENT`, `REVEAL_LEVEL`, `SHUFFLE_QUESTIONS`, `SHUFFLE_OPTIONS`; enums `Navigation(ALL_AT_ONCE="all_at_once", STEP_BACK="step_back", STEP_NO_BACK="step_no_back")`, `RevealMoment(NEVER="never", AT_END="at_end", AFTER_EACH="after_each")`, `RevealLevel(VERDICT="verdict", ANSWERS="answers", EXPLANATIONS="explanations")`, `Switch(OFF="off", ON="on")`.
  - `settings.is_flow_conflict(navigation: str, moment: str) -> bool`; `@dataclass(frozen=True) class Flow: navigation: str; moment: str; level: str; shuffle_questions: bool; shuffle_options: bool; conflict: bool`; `settings.flow(quiz: Quiz) -> Flow` (on conflict `moment` is `at_end`, `conflict` true).
  - `Attempt.selection_json` and `Attempt.settings_json`, both `JSONField(null=True)`.
  - `selection.Item = TypedDict(id: str, draw: str | None)`; `selection.RNG: random.Random = random.SystemRandom()`, replaced in tests; `selection.choose(snapshot: JSON, shuffle: bool) -> list[Item]`; `selection.given(snapshot: JSON, items: Sequence[Item]) -> list[dict]`; `selection.own_items(snapshot: JSON) -> list[Item]`; `selection.count(snapshot: JSON) -> int`.
  - `attempts.items_of(attempt: Attempt) -> list[Item]` (empty selection gives `own_items`); `attempts.questions_of(attempt) -> list[dict]`; `attempts.flow_of(attempt) -> Flow-shaped dict` (empty settings give defaults); `attempts.option_seed(attempt) -> str | None`.
  - `attempts.manifest_hash(question_ids: Sequence[str]) -> str`, same text as today for the same ids, so existing tokens stay valid.

- [ ] **Step 1: Write the failing tests**

```python
# tests/domain/test_flow_settings.py
def test_defaults_leave_a_quiz_as_it_is(quiz):
    flow = settings.flow(quiz)
    assert (flow.navigation, flow.moment, flow.level) == ("all_at_once", "never", "verdict")
    assert not flow.shuffle_questions and not flow.shuffle_options

def test_after_each_with_all_at_once_is_a_conflict():
    assert settings.is_flow_conflict("all_at_once", "after_each")
    assert not settings.is_flow_conflict("step_back", "after_each")

def test_conflict_from_a_global_change_falls_back_to_at_end(quiz):
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=None)
    settings.set_override(settings.NAVIGATION_MODE, quiz, "step_back", admin_id=None)
    settings.set_override(settings.NAVIGATION_MODE, quiz, None, admin_id=None)
    flow = settings.flow(quiz)
    assert flow.moment == "at_end" and flow.conflict

# tests/domain/test_selection.py
def test_without_shuffling_the_order_is_the_revision_order(): ...
def test_shuffling_changes_order_and_keeps_every_question(rng_seeded): ...

# tests/domain/test_attempts.py
def test_start_freezes_selection_and_settings(): ...  # selection_json lists ids, settings_json equals flow
def test_a_setting_change_does_not_touch_an_attempt_in_progress(): ...
def test_attempt_without_selection_plays_as_before():
    """Review Focus 1: update(selection_json=None, settings_json=None), submit scores all questions."""
def test_an_answer_to_a_question_not_given_changes_nothing(): ...
def test_start_with_a_missing_plugin_stores_no_attempt(): ...
```

And in `tests/api/test_admin_settings.py`: `test_global_form_refuses_after_each_with_all_at_once`, `test_quiz_form_refuses_conflict_of_effective_values` (global `all_at_once`, quiz sets `after_each`), `test_quiz_settings_warn_on_fallback` (page contains the warning text).

- [ ] **Step 2: Run them.** `make test` Expected: the new tests FAIL, on missing `settings.flow`.
- [ ] **Step 3: Implement settings.** Add the five keys to `CATALOGUE`, `SETTING_LABELS` and `VALUE_LABELS`. Both forms gain `clean()`: the global form tests its own posted values, the quiz form tests the values a saved form would resolve to (empty means global). The refusal is one form error: "Answers after each question need a one-by-one mode." `quiz_settings.html` shows the warning when `settings.flow(quiz).conflict`.
- [ ] **Step 4: Implement the freeze.** `attempts.start` writes `selection_json = {"items": choose(...), "seed": token or None}` and `settings_json`, with the seed set only when `shuffle_options` is on. It first calls `registry.get(..., include_disabled=True)` for every id in `revision.plugins_json`, so `UnknownPort` is raised before any write; the view renders after `start`. `_issue`, `_check_claims`, `_score`, `result_sources` and every loop in `play.py` go through `questions_of`. `_replacement` copies the old attempt's `settings_json` and seed. `public.py` shows `selection.count(snapshot)`.
- [ ] **Step 5: Run.** `make test` Expected: all pass, including the unchanged `tests/api/test_play.py` and `test_switch.py`.
- [ ] **Step 6: Commit.** `feat: flow settings, frozen on the attempt with its questions`

### Task 2: Shuffling options

**Files:**
- Modify: `app/plugins/questions/choice/plugin.py`, `app/api/rendering.py`, `app/api/play.py`, `docs/plugin-api.md`
- Test: `tests/contracts/test_choice.py`, `tests/contracts/test_matching.py`, `tests/api/test_play.py`

**Interfaces:**
- Consumes: `attempts.option_seed(attempt)` from Task 1.
- Produces: `question_html(..., option_seed: str | None = None)`; `quiz_settings` passed to `public_payload` gains `"shuffle_seed": f"{seed}:{question_id}"` when a seed exists.

- [ ] **Step 1: Write the failing tests.**

```python
def test_seed_shuffles_options_repeatably(): ...      # same seed, same order; another seed differs over 8 options
def test_yes_no_is_never_shuffled(): ...
def test_none_of_the_answers_stays_last(): ...         # offer_none stays a separate field, rendered after options
def test_no_seed_keeps_the_written_order(): ...
def test_matching_ignores_the_seed(): ...              # payload equal with and without
def test_rerender_after_a_refused_form_keeps_the_order(): ...  # API, no-JS try-again page
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** In `choice.public_payload`, `random.Random(seed).shuffle(options)` when standard and seed present, after the zip that attaches images. This generator is not a secret, and a seed is reproducible by design.
- [ ] **Step 4: Run.** `make test` Expected: pass.
- [ ] **Step 5: Commit.** `feat: options can be shuffled, except yes or no`

### Task 3: Navigation modes and progress

**Files:**
- Create: `app/plugins/quiz_flow/{__init__,apps,manifest,plugin}.py`, `app/api/assets/flow.js`, `tests/contracts/quiz_flow.py`, `tests/contracts/test_quiz_flow.py`
- Modify: `app/contracts/__init__.py`, `pyproject.toml`, `app/api/public.py`, `app/api/rendering.py`, `app/api/play.py`, `app/api/jinja2/public/_questions.html`, `app/plugins/theme_default/assets/theme.css`, `docs/plugin-api.md`, `app/plugins/CLAUDE.md`, `app/contracts/CLAUDE.md`
- Test: `tests/api/test_play_flow.py`

**Interfaces:**
- Consumes: `attempts.flow_of`, `attempts.questions_of`.
- Produces:
  - `class QuizFlowPlugin(Protocol): id; version; def modes(self) -> Sequence[str]; def client_options(self, mode: str, moment: str) -> JSON`, returning `{"step": bool, "back": bool, "check": bool}`. Port `"quiz_flow"`, plugin id `flow.basic`.
  - `rendering.flow_options(flow: Mapping) -> dict`; when the plugin is unavailable it returns `{"step": False, "back": False, "check": False}`, the all-at-once page.
  - Markup: `<form data-flow-step data-flow-back data-flow-check data-progress-step="Otázka {current} z {total}" data-progress-all="Zodpovězeno {current} z {total}">`; each question in `<section class="flow-question" data-question="<id>">`; `<div class="flow-progress" role="status" hidden><span></span><progress></progress></div>`; `<div class="flow-nav" hidden>` with Back and Next.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/contracts/quiz_flow.py, shared
def test_every_mode_has_options(self): ...
def test_all_at_once_is_not_step(self): ...
def test_check_only_with_step_and_after_each(self): ...
def test_no_back_only_in_step_no_back(self): ...

# tests/api/test_play_flow.py
def test_page_carries_the_mode(): ...                    # data-flow-step in step_back, not all_at_once
def test_controls_start_hidden_so_the_page_works_without_script(): ...  # every section has no hidden attr; nav and progress have it
def test_flow_script_is_served_and_included(): ...
def test_progress_texts_are_translated(lang): ...        # cs, en, uk
def test_unavailable_flow_plugin_gives_the_one_page_form(): ...
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement the plugin and markup.** Register the entry point in `pyproject.toml` beside `scoring.basic`, and in `SERVED_ASSETS`. The plugin is not in `EXACTLY_ONE` or `REQUIRED_CAPABILITIES`.
- [ ] **Step 4: Implement `flow.js`.** It runs on load and on `htmx:afterSwap`. In step mode it hides all sections but the current, shows nav and progress, and moves focus to the new section's first focusable heading (`tabindex="-1"`). Next on the last question is replaced by the form's submit button; before that the submit button is hidden. Back shows only when `data-flow-back`. In all-at-once mode it shows progress and counts a section as answered when it holds a checked input or has had a `change` event. Texts come from the data attributes; progress updates `role="status"`.
- [ ] **Step 5: Run.** `make test` Expected: pass. Browser check waits for Task 9.
- [ ] **Step 6: Commit.** `feat: navigation modes with a progress indicator`

### Task 4: Explanation

**Files:**
- Create: `app/domain/questions.py`
- Modify: `app/domain/authoring.py`, `app/domain/revision_diff.py`, `app/api/admin_forms.py`, `app/api/admin_quizzes.py`, `app/api/jinja2/admin/quiz_edit.html`
- Test: `tests/domain/test_authoring.py`, `tests/domain/test_revision_diff.py`, `tests/api/test_question_editor.py`, `tests/contracts/question_type.py`

**Interfaces:**
- Produces:
  - `questions.DEFAULT_POINTS`; `questions.apply_fields(question: dict, plugin, config, *, points=None, scoring=None, sources=None, explanation=None) -> None`, the body `save_question` has today; `questions.explanation_gaps(question: Mapping, locales: Sequence[str]) -> list[str]` (nothing filled gives `[]`, otherwise the locales without text); `questions.locales_to_fix(question, locales) -> list[str]`, moved from authoring and including those gaps; `questions.complete_locales(question, locales) -> list[str]`.
  - `QuestionCommonForm(..., strategies, locales, with_points=True)`, with fields `explanation_<locale>`; `form.explanation() -> dict[str, str]`.
  - `authoring.save_question(..., explanation: Mapping[str, str] | None = None)`. A question's `explanation` is `{locale: text}`, default `{}`.
  - Problem code `explanation_missing`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_explanation_filled_in_one_language_blocks_publication(): ...   # quiz cs+uk, cs only: problem for uk
def test_no_explanation_publishes(): ...
def test_explanation_in_no_quiz_language_is_no_gap(): ...               # en filled, quiz cs: []
def test_change_overview_lists_an_explanation_change(): ...
def test_explanation_is_kept_when_the_form_is_refused(): ...
def test_explanation_longer_than_the_limit_is_refused(): ...
def test_payload_never_has_the_explanation(self): ...                   # shared contract test
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** `authoring` imports from `questions`, and views use `questions.locales_to_fix`. `_rows` gains one `meta:explanation:<locale>` row per locale, so old revisions without the key compare as empty. `_problem_text` gets the new code. `explanation` is optional, so reading it uses `.get`.
- [ ] **Step 4: Run.** `make test` Expected: pass.
- [ ] **Step 5: Commit.** `feat: translated explanation on a question`

### Task 5: Revealing answers at the end

**Files:**
- Create: `app/domain/reveal.py`, `app/api/jinja2/public/_reveal.html`, `app/plugins/questions/choice/jinja2/choice/solution.html`, `app/plugins/questions/matching/jinja2/matching/solution.html`
- Modify: `app/contracts/__init__.py`, both question plugins, `tests/fixtures` demo question and `tests/contracts/demo_question_suite.py`, `app/api/play.py`, `app/api/rendering.py`, `app/api/jinja2/public/_result.html`, theme CSS, `docs/plugin-api.md`
- Test: `tests/contracts/question_type.py`, `tests/domain/test_reveal.py`, `tests/api/test_play_reveal.py`

**Interfaces:**
- Consumes: `attempts.flow_of`, `attempts.questions_of`, `_evaluate` from `attempts` (made public as `attempts.evaluate`).
- Produces:
  - `QuestionTypePlugin.render_solution(self, config: JSON, locale: str, answer: JSON | None) -> str`; `config` has image URLs filled by the API. Only the reveal path calls it.
  - `reveal.State`: `RIGHT`, `PARTIAL`, `WRONG`, `UNANSWERED`; `@dataclass(frozen=True) class QuestionReveal: question_id: str; state: State; earned: Decimal; maximum: Decimal; show_answers: bool; explanation: str | None`.
  - `reveal.of_question(question: Mapping, answer: JSON | None, level: str, locale: str) -> QuestionReveal`; `reveal.is_blank(answer: JSON | None) -> bool` (no key holds a non-empty value).
  - `rendering.reveal_context(question, revealed, answer, locale) -> dict` with `prompt`, `state_text`, `solution_html`, `explanation`.
  - `AttemptResult` is unchanged; `submit` view builds the list itself.

- [ ] **Step 1: Write the failing tests.**

```python
# shared contract
def test_render_solution_marks_the_correct_answer(self): ...
def test_render_solution_escapes_admin_text(self): ...
def test_render_solution_escapes_a_hostile_answer(self): ...
def test_render_solution_without_an_answer(self): ...

# tests/domain/test_reveal.py
def test_full_points_is_right(): ...
def test_part_of_the_points_is_partial_with_points(): ...
def test_zero_answered_is_wrong(): ...
def test_nothing_answered_is_unanswered(): ...
def test_pairs_left_on_the_placeholder_are_unanswered():
    """Review Focus 4: {"pair_a": "", "pair_b": ""} is blank."""
def test_verdict_level_shows_no_answers_or_explanation(): ...
def test_answers_level_shows_answers_only(): ...
def test_explanations_level_shows_both(): ...

# tests/api/test_play_reveal.py
def test_never_shows_no_list(): ...
def test_at_end_lists_only_the_given_questions(): ...
def test_at_end_with_explanations_shows_the_translation(lang): ...
def test_trick_question_shows_none_of_the_answers_as_correct(): ...
def test_repeated_submission_shows_stored_score_and_list_from_its_answers(): ...
def test_state_has_text_not_only_colour(): ...
def test_after_each_shows_the_list_on_the_result_page(): ...
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** The list appears when the frozen `moment` is `at_end` or `after_each`. **[plan's call]** The server cannot tell whether the page ran JavaScript, and the spec needs the list for a page without it, so a participant who already checked each question also sees the summary. `_try_again` is unchanged. A blank answer is passed as `None`. Explanation text is rendered with the class `explanation` (`white-space: pre-line`).
- [ ] **Step 4: Run.** `make test` Expected: pass.
- [ ] **Step 5: Commit.** `feat: reveal answers and explanations on the result`

### Task 6: Revealing after each question

**Files:**
- Modify: `app/urls.py`, `app/domain/attempts.py`, `app/api/play.py`, `app/api/jinja2/public/_questions.html`, `app/api/assets/flow.js`
- Test: `tests/api/test_play_check.py`

**Interfaces:**
- Consumes: `reveal.of_question`, `rendering.reveal_context`, `flow_options`.
- Produces:
  - `attempts.check(attempt_id: UUID, token: str, question_id: str, answer: JSON | None) -> tuple[Mapping, str]`, returning the question and the level; codes `reveal_not_allowed` (403) and `not_in_attempt` (403) in `STATUS` and `MESSAGES`.
  - Route `POST /a/<uuid:attempt_id>/check`, name `check`, csrf-exempt like `submit`; the form has `hx-post` on the button, `name="check_question"`, `value=<id>`, `hx-include="closest section, [name=attempt_token], [name=lang]"`, `hx-target` the section's reveal box.

- [ ] **Step 1: Write the failing tests.**

```python
def test_check_returns_the_reveal(): ...
def test_check_refuses_when_moment_is_at_end_or_never(moment): ...       # 403, no answer text
def test_check_refuses_a_question_not_given(): ...
def test_check_refuses_after_submission(): ...
def test_check_refuses_a_bad_token(): ...
def test_check_refuses_after_the_run_closed(): ...
def test_check_refuses_a_malformed_answer(): ...                          # 400
def test_check_writes_nothing(): ...                                      # django_assert_num_queries, no INSERT or UPDATE; attempt row unchanged
def test_check_uses_the_frozen_setting(): ...                             # admin turns it off after start: still allowed
def test_start_page_contains_no_correct_answer_or_explanation(): ...
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement the endpoint and the buttons.** Zkontrolovat starts `hidden`, and `flow.js` shows it when `data-flow-check`, disabled until the section has had a `change` event.
- [ ] **Step 4: Implement the lock in `flow.js`.** After a successful swap into a reveal box: for each input and select in that section with a value to send, append a hidden input with the same name and value, then disable all of them and the sortable handles. A disabled input would drop the answer from the submission. Going back shows the locked state.
- [ ] **Step 5: Run.** `make test` Expected: pass.
- [ ] **Step 6: Commit.** `feat: reveal after each question, locked on the page`

### Task 7: Banks and draw rows

**Files:**
- Create: `app/domain/banks.py`, `app/domain/migrations/0008_question_banks.py`, `app/api/admin_banks.py`, `app/api/jinja2/admin/banks.html`, `bank.html`, `bank_form.html`, `draw_form.html`, `tests/domain/test_banks.py`, `tests/domain/test_draws.py`, `tests/api/test_admin_banks.py`
- Modify: `app/domain/models.py`, `app/domain/authoring.py`, `app/domain/quiz_state.py`, `app/domain/revision_diff.py`, `app/domain/selection.py`, `app/api/admin_urls.py`, `app/api/admin_quizzes.py`, `app/api/admin_forms.py`, `app/kernel/middleware.py`, `app/api/jinja2/admin/base.html`, `quiz_edit.html`, `_diff.html`, `question_form.html`, `app/domain/CLAUDE.md`, `app/api/CLAUDE.md`

**Interfaces:**
- Consumes: `questions.apply_fields`, `questions.locales_to_fix`, `questions.complete_locales`, `QuestionCommonForm(with_points=False)`.
- Produces:
  - Models `QuestionBank(id uuid7, name, created_by, created_at)` table `question_bank`; `BankQuestion(id uuid7, bank FK PROTECT, question_json, tags JSON list, created_at)` table `bank_question`.
  - `banks.create(name, *, admin_id) -> QuestionBank`; `banks.rename`; `banks.delete(bank, *, admin_id)`, raising `BankInUse(quiz_titles)` when a draft or the latest published revision of any quiz has a row on it; `banks.save_question(bank, question_id, type_id, config, *, scoring, sources, explanation, tags, new_id) -> str`, raising `NoCompleteLanguage`; `banks.delete_question`; `banks.tags_of(bank) -> list[str]`; `banks.normal_tag(text) -> str` (`strip().casefold()`).
  - `banks.pool(row: Mapping, locales: Sequence[str]) -> list[dict]`: usable questions ordered by id, with `settings.points` from the row and no tags; `banks.usable_count(row, locales) -> tuple[int, int]`, returning usable and all matching the tag.
  - Draft shape: `snapshot_json["draws"]`, a list of `{"id", "bank_id", "bank_name", "tag", "count", "points", "position"}`, where `position` is how many own questions come before the row. Published rows add `"pool"`.
  - `authoring.save_draw(quiz, draw_id, *, bank_id, tag, count, points, position) -> str`; `authoring.delete_draw`; `authoring.editable_draws(quiz) -> list[dict]`; `authoring.banks_changed(quiz) -> bool`; `authoring.has_changes(quiz) -> bool` (draft exists, or banks changed).
  - `selection.assign(rows: Sequence[Mapping]) -> dict[str, list[str]] | None`: for each row id, the question ids filling its places with no repeat, or `None` when impossible. Augmenting-path bipartite matching over places in `RNG`-shuffled order; publication and drawing both use it.
  - Problem codes `draw_not_enough` and `draw_bank_missing`, with `detail` the row's bank name and tag.
  - `RevisionDiff` gains `draws: list[FieldChange]` for row settings, and `bank_added`, `bank_removed`, `bank_changed: list[QuestionChange]` with `number` 0.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/domain/test_banks.py
def test_question_needs_one_complete_language(): ...
def test_tags_are_trimmed_and_compared_ignoring_case(): ...
def test_incomplete_explanation_makes_a_language_incomplete(): ...
def test_bank_in_use_cannot_be_deleted_and_names_the_quiz(): ...
def test_deleting_a_question_leaves_published_revisions_unchanged(): ...

# tests/domain/test_draws.py
def test_missing_language_is_left_out_of_the_pool(): ...
def test_usable_count_shows_17_of_20(): ...
def test_publication_copies_the_pool_with_row_points(): ...
def test_max_score_is_own_plus_count_times_points(): ...
def test_blocked_only_when_rows_cannot_be_filled(): ...
def test_overlapping_rows_are_checked_together(): ...       # two rows of 2 over 3 questions: blocked; over 4: published
def test_greedy_would_fail_but_assign_succeeds(): ...       # row A any of {1,2}, row B only {1}
def test_quiz_with_only_draw_rows_publishes():
    """Review Focus 5."""
def test_language_added_after_publication_recounts_and_blocks():
    """Review Focus 5."""
def test_bank_edit_leaves_revision_and_attempt_unchanged(): ...
def test_bank_edit_shows_unpublished_changes(): ...         # quiz_state.of(quiz).has_changes, main button
def test_bank_change_can_be_published_without_a_draft(): ...
def test_nothing_to_discard_when_only_a_bank_changed(): ...
def test_change_overview_lists_added_changed_removed_bank_questions(): ...
def test_returning_to_an_old_revision_keeps_rows_and_rereads_the_bank(): ...
def test_returning_with_a_deleted_bank_blocks_publication(): ...
def test_duplicate_copies_rows(): ...
def test_stale_publication_refused_after_a_bank_edit(): ...  # expected_hash

# tests/api/test_admin_banks.py
def test_banks_require_login(): ...
def test_bank_editor_has_three_languages_tags_and_no_points(): ...
def test_image_upload_works_on_the_bank_editor(): ...        # multipart accepted on bank question routes
def test_multipart_refused_on_other_bank_routes(): ...
def test_double_save_with_one_form_key_creates_one_question(): ...
def test_quiz_questions_page_shows_the_row_and_usable_count(): ...
def test_draw_form_refuses_count_and_points_out_of_range(): ...
def test_row_appears_at_its_position(): ...
def test_archived_quiz_cannot_get_a_row(): ...
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement models and bank services.** `tests/test_layers.py` holds for all of them. `banks.save_question` uses `questions.apply_fields` and all of `PUBLIC_LOCALES` passed by the view. The stored question id is the row's uuid as text.
- [ ] **Step 4: Implement rows in authoring.** `future_snapshot` adds `"draws"` with pools, so `snapshot_hash` and the change overview see bank edits. `get_draft`, `use_as_draft` and `duplicate_quiz` copy rows without pools. `_freeze` records versions for pool questions in `plugins_json` and adds row maxima to `max_score`, as `count * strategy.max_score(pool[0]["settings"])`. `publish` calls `get_draft` when there is no draft and `banks_changed` is true, then behaves as today. `quiz_state.of` uses `has_changes`; `can_discard` stays `has_draft and published`. `_publication_problems` uses `has_changes`. `validate_for_publication` reports `no_questions` only with neither questions nor rows, and always reads `.get("draws", [])`.
- [ ] **Step 5: Implement the admin.** Top-level item Banky between Kvízy and Nastavení. `admin_banks.py` reuses `_form_with_uploads`, `_strategies`, `_enabled_plugin` and `_add_menu` from `admin_quizzes.py`. `question_form.html` gets a `back_url` and a tags field. The multipart gate allows `/admin/banks/<id>/questions/...`. The draw form has bank, tag (free text with a `datalist` of existing tags), count, points, and "Po otázce" for position. On the quiz page rows sit among questions by `position` and link to their form, showing "usable N of M".
- [ ] **Step 6: Run.** `make test` Expected: pass.
- [ ] **Step 7: Commit.** `feat: question banks and draw rows`

### Task 8: Drawing and switching

**Files:**
- Modify: `app/domain/selection.py`, `app/domain/attempts.py`, `app/api/public.py`
- Test: `tests/domain/test_selection.py`, `tests/domain/test_attempts.py`, `tests/api/test_switch.py`, `tests/integration/test_banks_and_flow.py`

**Interfaces:**
- Consumes: `selection.assign`, published `draws[*].pool`, `attempts.items_of`.
- Produces: `selection.choose` handles rows; `selection.given` takes a drawn question from its row's pool, so points are the row's; `selection.carry_over(old_snapshot: JSON, old_items: Sequence[Item], new_snapshot: JSON, shuffle: bool) -> list[Item]`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_each_attempt_gets_count_distinct_questions(): ...
def test_overlapping_rows_never_repeat_a_question(): ...          # 200 draws with a seeded RNG
def test_every_attempt_has_the_same_maximum(): ...
def test_draw_takes_the_rows_position(): ...                      # own, drawn x3, own
def test_shuffle_mixes_the_whole_list(): ...
def test_same_question_in_two_rows_scores_with_its_rows_points():
    """Review Focus 2."""
def test_scoring_uses_the_frozen_selection_after_a_new_publication(): ...

def test_switch_keeps_drawn_questions_still_in_the_pool(): ...
def test_switch_draws_more_when_a_row_grew(): ...
def test_switch_drops_surplus_when_a_row_shrank(): ...
def test_switch_removes_questions_of_a_removed_row(): ...
def test_switch_fills_a_new_row(): ...
def test_switch_keeps_answers_to_unchanged_and_marks_changed(): ...
def test_switched_attempt_keeps_its_settings(): ...
def test_public_page_counts_drawn_questions(): ...
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** `carry_over` keeps own questions in the new order, and for each new row keeps old items of the same row whose id is in the new pool, up to `count`, then fills the rest through `assign` with those fixed. `_moved_answers` takes the given lists of both attempts instead of snapshots, with its comparison unchanged.
- [ ] **Step 4: Run.** `make test` Expected: pass.
- [ ] **Step 5: Commit.** `feat: attempts draw from banks and keep them on switching`

### Task 9: Documents, translations and verification

**Files:**
- Create: `docs/_architecture/adr/0041-draw-rows-and-flow-settings.md`
- Modify: `docs/_architecture/plugins/question-types.md` (`FR-18`, `FR-23`), `plugins/quiz-flow.md`, `plugins/theme-default.md`, `modules/domain.md`, `modules/api-ui.md`, `modules/contracts.md`, `data-model.md`, `acceptance-criteria.md`, `roadmap.md`, `adr/README.md`, `docs/plugin-api.md`, `CLAUDE.md`, the `CLAUDE.md` of touched directories, `.po` and `.mo` catalogues

- [ ] **Step 1: Write the documents.** ADR-0041 status accepted: draw rows set points; flow settings apply immediately and are frozen on the attempt; "after the run closes" moves to Stage C. Roadmap: B3 done, and under C add the AC-18 check and the after-close reveal with a lasting result page. New acceptance rows from AC-30, one for each item in the spec's Acceptance section. Next free numbers are read from the documents.
- [ ] **Step 2: Translate.** `make messages`, fill cs, en and uk. `tests/test_translations.py` Expected: pass.
- [ ] **Step 3: Run the gates.** `make quality`, then `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke` Expected: all pass, smoke with no FAIL.
- [ ] **Step 4: Walk through in a browser.** Rebuild `kvizotron-browser` with `up --build`, keeping its data, and add a new quiz. At 360 px and on desktop, light and dark: bank with images and tags in three languages; a quiz with own questions and two overlapping rows; each navigation mode by mouse and by keyboard; JavaScript off; all three levels at the end; after each question with a right, a wrong and a skipped answer; a locked answer submitted and counted (Review Focus 3); a bank edit showing unpublished changes; a revision switch mid-attempt. An attempt started on the old build still submits (Review Focus 1). Fix what shows up, each with a test first where it can have one.
- [ ] **Step 5: Commit.** `docs: milestone B3 done`

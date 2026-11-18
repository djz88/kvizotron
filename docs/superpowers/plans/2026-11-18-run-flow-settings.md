# A Run Keeps Its Flow and Sources Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A run copies navigation, page size, reveal, shuffle and sources from its quiz when it is planned or opened and reads them from itself; a quiz settings save or quiz type change that would change them asks whether to apply the change to the quiz's planned or open run (TD-101).

**Architecture:** New `QuizRun.flow_json`, filled by `run_flow.snapshot(quiz)` in `run_schedule.plan` and `authoring.open_run` and by a data migration for existing runs. A read module `run_flow` (no imports beyond `settings` and `models`, so `rewards`, `results` and `data_policy` can use it) replaces every live read. A change module `run_flow_change` computes the offer for the run and applies the admin's answer at the end of the transaction that saved the quiz; the old "planned or open run" clashes of `setting_rules.clashes` become per-run reasons that only limit the answer to "from the next run".

**Tech Stack:** Django, Jinja2, pytest (`make test`), gettext (`make messages`).

**Spec:** `docs/superpowers/specs/2026-11-18-run-flow-settings-design.md`

## Global Constraints

- Kept keys, exactly these seven: `navigation_mode`, `page_size`, `reveal_moment`, `reveal_level`, `shuffle_questions`, `shuffle_options`, `show_sources` (`settings.NAVIGATION_MODE` … `settings.SHOW_SOURCES`).
- The run stores resolved quiz-level values; a question's own value still wins where it has one (ADR-0042).
- Test runs (`kind == TEST`), preview (`app/domain/preview.py`) and the quiz settings page's own flow warning keep following the quiz live.
- Revision switches and plan edits (`run_schedule.update_plan`) never write `flow_json`.
- Asked about: the quiz's planned or open normal run only (at most one, constraint `one_open_run_per_quiz`). Closed and archived runs are never asked and never changed.
- A global settings change never changes a planned or open run.
- Nothing is saved half: the question is asked before anything is stored (the save runs in one transaction that rolls back when an answer is needed); cancel saves nothing.
- Attempts keep what they froze in `attempt.settings_json` / `selection_json`.
- No module-level import cycle (`tests/test_layers.py`); `app/domain` never imports `app/api`.
- Docs in English; admin texts cs and en (`make messages`, `msgstr` filled); tests first; `make quality` green.
- Commits without a `Claude-Session` line; docs without local paths or LAN addresses; never touch Docker stacks `kvizotron-browser` or `kvizotron-tmp`.

## Review Focus

1. A save that changes no kept value (only the identifier, colours, or the Basic view where the flow fields are not sent) on a quiz whose run differs from the quiz after an earlier "next run" answer must not ask — Task 3 `test_only_the_keys_this_save_changed_are_offered`, Task 4 `test_an_unrelated_save_asks_nothing`.
2. A plan edit after a "next run" answer keeps the run's values — Task 1 `test_a_plan_edit_keeps_the_kept_values`.
3. The run closes between the question and the answer — the save goes through and the closed run is untouched — Task 4 `test_a_run_closed_meanwhile_saves_without_asking`.
4. An attempt in progress when the change is applied to the run keeps its frozen settings; only new attempts change — Task 3 `test_an_attempt_in_progress_keeps_its_settings`.
5. A missing, unknown or forged answer: asked again with nothing saved; "run" on a run that cannot take the change is 409 with nothing saved — Task 4 `test_an_unknown_answer_asks_again`, `test_a_forged_run_answer_on_a_refused_run_is_409`.

---

### Task 1: The run keeps the values

**Files:**
- Modify: `app/domain/models.py` (`QuizRun`), `app/domain/settings.py` (`flow`), `app/domain/run_schedule.py` (`plan`), `app/domain/authoring.py` (`open_run`)
- Create: `app/domain/run_flow.py`, `app/domain/migrations/0028_run_flow.py`
- Create: `docs/_architecture/adr/0069-run-keeps-flow-settings.md` (+ row in `adr/README.md`); add `AC-185` to `docs/_architecture/acceptance-criteria.md`; `quiz_run` row in `docs/_architecture/data-model.md`
- Test: `tests/domain/test_run_flow.py`, `tests/domain/test_migration_0028.py`

**Interfaces:**
- Produces: `QuizRun.flow_json = models.JSONField(default=dict)`; `settings.flow_of(values: Mapping[str, str]) -> Flow` (today's `flow` logic over given values; `flow(quiz)` calls it); `run_flow.KEYS: tuple[str, ...]` (the seven keys in the order above); `run_flow.snapshot(quiz: Quiz) -> dict[str, str]` (`settings.resolve(key, quiz)` per key); `run_flow.of(run: QuizRun) -> dict[str, str]` (a TEST run: `snapshot(run.quiz)`; otherwise `flow_json`, where a missing key or a stored value no longer in `settings.CATALOGUE[key].choices` is resolved from the quiz); `run_flow.flow(run: QuizRun) -> settings.Flow` (`settings.flow_of(of(run))`).

- [ ] **Step 1: Failing tests** in `tests/domain/test_run_flow.py`, each docstring starting `AC-185:`:

```python
def test_a_planned_run_keeps_the_quiz_values():
    # quiz override reveal_moment "at_end"; run_schedule.plan(...)
    assert set(run.flow_json) == set(run_flow.KEYS)
    assert run.flow_json == run_flow.snapshot(quiz)

def test_an_opened_run_keeps_the_quiz_values():            # same via authoring.open_run

def test_a_quiz_change_after_opening_does_not_reach_the_run():
    # open; set_override(NAVIGATION_MODE, quiz, "pages")
    assert run_flow.of(run)[settings.NAVIGATION_MODE] == before[settings.NAVIGATION_MODE]
    assert run_flow.flow(run).navigation == before[settings.NAVIGATION_MODE]

def test_a_test_run_follows_the_quiz():                    # run_links test run; change override → of() shows it

def test_a_plan_edit_keeps_the_kept_values():
    # plan; set_override(REVEAL_MOMENT, quiz, "never"); run_schedule.update_plan(run, same times)
    assert run.flow_json[settings.REVEAL_MOMENT] == old

def test_a_revision_switch_keeps_the_values():             # open, publish rev 2, switch the run → flow_json unchanged

def test_a_value_no_longer_offered_falls_back_to_the_quiz():
    # run.flow_json[PAGE_SIZE] = "999"
    assert run_flow.of(run)[settings.PAGE_SIZE] == settings.resolve(settings.PAGE_SIZE, quiz)
```

`tests/domain/test_migration_0028.py` (pattern of `test_migration_0026.py`): a quiz override `reveal_moment=never`, a global row `navigation_mode=pages`, a quiz override not offered (`page_size=999`) → after `0028` the normal run has `never`, `pages` and the global/default `page_size`; a test run keeps `{}`.

- [ ] **Step 2: Run** `uv run pytest tests/domain/test_run_flow.py tests/domain/test_migration_0028.py -q` — Expected: FAIL (no `run_flow`, no field).
- [ ] **Step 3: Implement.** Field with a one-line comment like its neighbours. Migration `0028_run_flow`: `AddField` + `RunPython(fill, migrations.RunPython.noop)`; it stands alone (as `0013` does): per key the choices and default copied from `settings.CATALOGUE` today; for each run with `kind != "test"`: quiz override if offered, else the global row if offered, else the default. `plan` and `open_run` pass `flow_json=run_flow.snapshot(quiz)`; `update_plan` does not touch it.
- [ ] **Step 4: Docs.** ADR-0069 (MADR as ADR-0068): context = TD-101; decision = the spec's decisions 1–3 and the agent's decisions; consequences incl. that run-level clashes no longer block a quiz or global save (Task 4) and AC-18's new wording. AC-185 row (phase D): "A run keeps navigation, page size, reveal, shuffle and sources from when it was planned or opened; a quiz settings save or quiz type change that changes them asks whether the planned or open run takes the change, offering only the next run when the run's rules forbid it; a global change applies from each quiz's next run." Data model: `flow_json` (the seven values copied when planned or opened, ADR-0069; a test run reads the quiz live).
- [ ] **Step 5: Run** `make lint && make test && uv run pytest tests/test_docs.py -q` — Expected: PASS.
- [ ] **Step 6: Commit** `feat(runs): a run keeps navigation, reveal, shuffle and sources (TD-101)`.

### Task 2: Every reader reads the run

**Files:**
- Modify: `app/domain/attempts.py:237` (`start`), `app/api/rendering.py:242` (`result_sources`), `app/api/play.py:710`, `app/api/admin_preview.py:220`, `app/domain/rewards.py:217` (`conflicts`), `app/domain/results.py:165,193` (`ensure_run_allowed`, `set_display`), `app/domain/data_policy.py:177,185` (`after_close_conflicts`, `ensure_run_allowed`), `app/domain/run_schedule.py` (`_stateless_conflicts`, `plan`, `update_plan`), `app/domain/authoring.py` (`open_run`)
- Test: `tests/domain/test_run_flow_readers.py` (new), `tests/api/test_run_flow_sources.py` (new)

**Interfaces:**
- Consumes: `run_flow.of`, `run_flow.flow`, `run_flow.snapshot` (Task 1).
- Produces: `rendering.result_sources(questions, sources: str, locale: str)` — `sources` is the quiz-level value (the run's in play, the quiz's in preview); a question's own `settings.question_value(SHOW_SOURCES, question)` wins. `data_policy.after_close_conflicts(moment: str, profile: str)`; `data_policy.ensure_run_allowed(quiz, data, rules, snapshot, *, reveal_moment: str)`; `results.ensure_run_allowed(chosen, profile, *, reveal_moment: str)` (the `quiz` parameter goes: it only read the reveal). Plan and open pass `run_flow.snapshot(quiz)[REVEAL_MOMENT]` (compute the snapshot once and reuse it for `flow_json`); `update_plan` and `_stateless_conflicts` pass `run_flow.of(run)[REVEAL_MOMENT]`; `set_display` and `rewards.conflicts` read `run_flow.of(run)`.

- [ ] **Step 1: Failing tests** (docstrings `AC-185:`; change the quiz with `settings.set_override` directly, as an earlier "next run" answer would leave it):

```python
def test_a_new_attempt_plays_by_the_run():
    # open (navigation step_back, shuffle_options off); quiz → all_at_once, shuffle_options on
    started = attempts.start(run, ...)
    assert started.attempt.settings_json["navigation"] == "step_back"
    assert started.attempt.selection_json["seed"] is None

def test_rewards_conflicts_read_the_run():          # run with a rule, kept at_end; quiz after_each → conflicts(run) == []
def test_set_display_judges_the_run_reveal():       # kept at_end; quiz after_each; set_display(visibility "live") passes
def test_a_plan_edit_judges_the_kept_reveal():      # kept at_end; quiz after_close; update_plan with profile "score" passes
def test_opening_a_plan_judges_the_kept_reveal():   # same, run_schedule.settle at starts_at → run OPEN, no run.open_refused
```

`tests/api/test_run_flow_sources.py`: finished attempt, quiz `show_sources` then set to `off` → the result page (`/v/<token>` and the result after submit) still lists the sources; a question with its own `show_sources: off` hides them; preview result follows the quiz.

- [ ] **Step 2: Run** the new tests — Expected: FAIL.
- [ ] **Step 3: Implement** the interface changes above; existing callers and tests of the changed signatures follow.
- [ ] **Step 4: Run** `make lint && make test` — Expected: PASS (preview and test-link suites unchanged).
- [ ] **Step 5: Commit** `fix(runs): attempts, sources and run checks read the run's values (TD-101)`.

### Task 3: The offer and the answer (domain)

**Files:**
- Modify: `app/domain/setting_rules.py` (new `run_clashes`; `clashes` unchanged in this task)
- Create: `app/domain/run_flow_change.py`
- Test: `tests/domain/test_run_flow_change.py`

**Interfaces:**
- Consumes: `run_flow.KEYS`, `run_flow.of`, `run_flow.snapshot`.
- Produces:
  - `setting_rules.run_clashes(run: QuizRun, values: Mapping[str, str]) -> list[Clash]` — `values` are the run's seven values after a change; in this order: `FLOW` (`is_flow_conflict(navigation, moment)`), `RUN_PROFILE` (moment `after_close` and the run's profile does not keep all answers), `RUN_BOARD` (moment `after_each` and `results.needs_participant(run)`), `RUN_REWARDS` (moment `after_each` and `rewards.has_rules(run)`); each `Clash(reason, settings.REVEAL_MOMENT)`.
  - `run_flow_change.FIELD = "flow_choice"`, `RUN = "run"`, `NEXT = "next"`.
  - `@dataclass(frozen=True) class Change: key: str; kept: str; new: str`
  - `@dataclass(frozen=True) class Offer: run: QuizRun; changes: list[Change]; refused: list[Clash]` (`refused` empty = the run can take it).
  - `class ChoiceNeeded(Exception)` and `class FlowRefused(Exception)`, each with `.offer: Offer`.
  - `offer_for(quiz: Quiz, before: Mapping[str, str], after: Mapping[str, str]) -> Offer | None` — the quiz's SCHEDULED or OPEN normal run; `changes` = keys where `before != after` and the run's `of(run)` value `!= after`, in `KEYS` order; `refused = run_clashes(run, of(run) | {c.key: c.new})`; `None` without such a run or without changes.
  - `settle(quiz: Quiz, before: Mapping[str, str], choice: str | None, *, admin_id: str) -> None` — called last inside the caller's `transaction.atomic()` that saved the quiz; `after = run_flow.snapshot(quiz)`; no offer → return; `choice` not `RUN`/`NEXT` → `ChoiceNeeded`; `NEXT` → return; `RUN` with `refused` → `FlowRefused`; `RUN` otherwise → the run, locked with `select_for_update`, gets `flow_json = of(run) | changes`, audit `run.flow_applied` (entity the run, details `{"keys": [...]}` only).

- [ ] **Step 1: Failing tests** (docstrings `AC-185:`):

```python
def test_without_a_live_run_nothing_is_offered():          # closed run, archived run, test run → None
def test_an_unchanged_value_offers_nothing():              # before == after → None
def test_a_value_the_run_already_has_offers_nothing():
def test_only_the_keys_this_save_changed_are_offered():
    # run kept reveal "at_end" while quiz is "never" (earlier "next"); this save changes only shuffle_questions
    assert [c.key for c in offer.changes] == [settings.SHUFFLE_QUESTIONS]
def test_no_answer_rolls_the_save_back():
    with pytest.raises(run_flow_change.ChoiceNeeded), transaction.atomic():
        settings.set_override(settings.NAVIGATION_MODE, quiz, "pages", admin_id=ADMIN_ID)
        run_flow_change.settle(quiz, before, None, admin_id=ADMIN_ID)
    assert settings.quiz_override(settings.NAVIGATION_MODE, quiz) is None
def test_next_leaves_the_run():
def test_run_writes_only_the_changed_keys_and_audits_keys_only():
def test_a_run_with_rewards_cannot_take_after_each():
    assert [c.reason for c in offer.refused] == [setting_rules.RUN_REWARDS]
    # settle(RUN) → FlowRefused; settle(NEXT) passes
def test_run_clashes_follow_the_old_run_rules():            # RUN_PROFILE, RUN_BOARD, FLOW cases, one each
def test_an_attempt_in_progress_keeps_its_settings():       # start, apply navigation change with RUN, resume → old navigation; a new attempt → new
```

- [ ] **Step 2: Run** `uv run pytest tests/domain/test_run_flow_change.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces; `run_flow_change` may import `setting_rules`, `run_flow`, `audit`, `models`; `run_flow` imports neither.
- [ ] **Step 4: Run** `make lint && make test` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(runs): offer a quiz change to the planned or open run (TD-101)`.

### Task 4: The quiz settings page asks

**Files:**
- Modify: `app/domain/setting_rules.py` (`clashes(values)` without `quiz` and without run checks; `_live_runs` goes), `app/api/admin_forms_quiz.py` (`_refuse_clashes`), `app/domain/quiz_types.py` (calls of `clashes`), `app/api/admin_quizzes.py` (`quiz_settings`)
- Create: `app/api/jinja2/admin/quiz_settings_confirm.html`, `app/api/jinja2/admin/_run_flow_choice.html`, a helper `run_offer_context(offer: run_flow_change.Offer) -> dict[str, Any]` in `app/api/admin_quizzes.py`
- Modify: `docs/_architecture/acceptance-criteria.md` (AC-18), locale files (`make messages`)
- Test: `tests/api/test_run_flow_confirm.py` (new); convert the tests that pin a refusal because of a live run: `tests/domain/test_setting_rules.py` (`…open_run_showing_a_board_is_run_board`, `…not_repeated_beside…`, `…scheduled_run_with_rewards_is_run_rewards`, `…live_score_run_is_run_profile`, `test_live_run_with_answers_does_not_refuse_after_close`) → `run_clashes` cases plus "the clash list is empty"; `tests/domain/test_quiz_types.py:130-133` → the type applies and the run keeps its values; `tests/contracts/quiz_type.py` (drop the `of_runs` filter); `tests/api/test_admin_rewards.py:408` and `tests/api/test_results_forms.py:80` → the save asks and offers only the next run, with the same reason sentence. None is deleted; a converted test keeps its `AC-xx` docstring.

**Interfaces:**
- Consumes: `run_flow_change.settle`, `ChoiceNeeded`, `FlowRefused`, `FIELD`, `RUN`, `NEXT`, `Offer`; `run_flow.snapshot`; `admin_forms.clash_message`, `setting_label`, `setting_value_label`; `run_tabs.status_label`.
- Produces: `setting_rules.clashes(values: Mapping[str, str]) -> list[Clash]`; `run_offer_context(offer)` → `{"number": run_no, "status": status label, "changes": [{"label", "kept", "new"}], "refused": [clash messages, deduplicated]}`; partial `admin/_run_flow_choice.html` taking `run_offer` (used again in Task 5).
- `quiz_settings` POST: one `transaction.atomic()` around `before = run_flow.snapshot(quiz)`, `form.apply_to`, the override loop, `save_colours` and `settle(quiz, before, request.POST.get(FIELD), admin_id=…)`; `ChoiceNeeded` → confirm page 200, `FlowRefused` → confirm page 409; the `IntegrityError` handling stays.
- Confirm page: crumb back to the settings, the hidden posted fields (from `request.POST.lists()`, without `csrfmiddlewaretoken` and `flow_choice`), the partial, `Save` button, `Cancel` link to `admin_quiz_settings` (nothing saved). Partial: radios `name="flow_choice"` `required`; without `refused` both, with `refused` the reason list and only `next` (checked).

Copy (msgid en → cs):

| Where | en | cs |
|---|---|---|
| h1 | Apply the change to run %(number)s too? | Použít změnu i pro běh %(number)s? |
| intro | Run %(number)s (%(status)s) was planned or opened with these values: | Běh %(number)s (%(status)s) byl naplánován nebo otevřen s těmito hodnotami: |
| change line | `<strong>label</strong>: kept → new` | same |
| radio run | Also for run %(number)s: its new attempts, and the sources on its result pages | I pro běh %(number)s: jeho nové pokusy a zdroje na stránkách jeho výsledků |
| radio next | Only from the next run; run %(number)s keeps its values | Až od dalšího běhu; běh %(number)s si nechá své hodnoty |
| refused | Run %(number)s cannot take this change: | Běh %(number)s tuto změnu převzít nemůže: |
| note | Attempts already started keep the navigation, reveal and shuffle they started with. | Pokusy, které už začaly, si nechají průchod, odhalení a míchání, se kterými začaly. |

AC-18 new text: "Reveal after each question cannot reach a run with a visible scoreboard or rewards: planning or opening such a run is refused with an explanation, and a quiz change offers it to such a run only from the next run, with the reason; in a run without them the participant sees the solution after each question."

- [ ] **Step 1: Failing tests** in `tests/api/test_run_flow_confirm.py` (docstrings `AC-185:`), quiz with an open run unless said:

```python
def test_a_change_the_run_would_take_asks_first():     # POST navigation change → 200, h1 text, change line; override not saved
def test_answering_run_applies_it():                   # + flow_choice=run → 302; override saved; run.flow_json changed
def test_answering_next_keeps_the_run():               # + flow_choice=next → 302; override saved; flow_json unchanged
def test_the_confirm_page_repeats_the_posted_fields(): # every posted field is a hidden input, no csrfmiddlewaretoken twice; cancel href is the settings page
def test_a_run_with_rewards_is_offered_only_next():    # rule on run, reveal after_each → reason sentence, no input value="run"
def test_a_forged_run_answer_on_a_refused_run_is_409():# flow_choice=run → 409; nothing saved
def test_an_unknown_answer_asks_again():               # flow_choice=maybe → 200 page; nothing saved
def test_an_unrelated_save_asks_nothing():             # only slug changes, run differs from quiz after an earlier "next" → 302
def test_a_run_closed_meanwhile_saves_without_asking():# close run, then POST flow_choice=run → 302; closed run's flow_json unchanged
def test_a_global_change_does_not_reach_a_live_run():  # POST /admin/settings reveal after_each with a live run with rules → 302; run kept value unchanged
```

- [ ] **Step 2: Run** `uv run pytest tests/api/test_run_flow_confirm.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement**, convert the listed tests, `make messages`, fill cs `msgstr`.
- [ ] **Step 4: Run** `make lint && make test && uv run pytest tests/test_docs.py tests/test_translations.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(admin): saving quiz settings asks whether the run takes the change (TD-101)`.

### Task 5: Quiz type and global page; close TD-101

**Files:**
- Modify: `app/domain/quiz_types.py` (`Preview.live_run` → `run_offer: run_flow_change.Offer | None`; `apply(..., flow_choice: str | None = None)`), `app/api/admin_quiz_types.py`, `app/api/jinja2/admin/quiz_type_confirm.html` (the `#live-run` notice goes; the partial goes inside the form), `app/api/jinja2/admin/settings.html`, locale files
- Modify: `docs/_architecture/modules/api-ui.md` ("Where things are set": the seven values are copied to a run when planned or opened, ADR-0069), `app/domain/CLAUDE.md` (`run_flow`, `run_flow_change`, `setting_rules` without run clashes, `quiz_types.run_offer`), `app/api/CLAUDE.md` (type overview and quiz settings confirm), `docs/_architecture/TECH_DEBT.md` → `make tech-debt-resolve id=TD-101` and a `- Resolution:` line in the archive
- Test: `tests/domain/test_quiz_types.py`, `tests/api/test_admin_quiz_types.py` (`test_overview_warns_about_a_live_run_and_the_content` → the content warning stays, the run part becomes the choice), `tests/api/test_run_flow_confirm.py`

**Interfaces:**
- Consumes: Task 3 and Task 4 interfaces.
- Produces: `Preview.run_offer = run_flow_change.offer_for(quiz, run_flow.snapshot(quiz), {key: final[key] for key in run_flow.KEYS})`; `apply` takes `before = run_flow.snapshot(quiz)` at the start of its transaction and calls `settle(quiz, before, flow_choice, admin_id=admin_id)` after its writes. The view passes `request.POST.get(FIELD)`; `ChoiceNeeded` → overview 400, `FlowRefused` → overview 409, nothing written in either. `remove` writes no value, so it never asks.
- Global page sentence, a `<p id="runs-keep">` under the h1 — en "Navigation, answer reveal, shuffling and sources changed here apply from each quiz's next run; planned and open runs keep their values." cs "Průchod, odhalení odpovědí, míchání a zdroje změněné tady platí od dalšího běhu každého kvízu; naplánované a otevřené běhy si nechají své hodnoty."

- [ ] **Step 1: Failing tests** (docstrings `AC-185:`):

```python
def test_type_overview_offers_the_run():            # live run, type changes navigation → radios on the overview, no #live-run
def test_type_apply_with_run_applies_to_the_run():   # POST confirm=1, flow_choice=run → run.flow_json has the type's values
def test_type_apply_without_an_answer_writes_nothing():  # confirm=1, no flow_choice → 400; quiz_type and overrides unchanged
def test_type_without_a_change_for_the_run_asks_nothing():  # no live run, or same values → no radios, applies as before
def test_type_remove_asks_nothing():                 # remove with a live run → 302; flow_json unchanged
def test_global_page_says_runs_keep_their_values():  # GET /admin/settings?lang=en → the sentence
```

- [ ] **Step 2: Run** the new tests — Expected: FAIL.
- [ ] **Step 3: Implement**, `make messages`, cs `msgstr`; docs and TD-101 resolution.
- [ ] **Step 4: Run** `make quality` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(admin): a quiz type change asks about the run; global page says runs keep values (TD-101)`.

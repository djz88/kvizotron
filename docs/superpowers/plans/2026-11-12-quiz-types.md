# Quiz types — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin picks a quiz type (Practice, Final test, Mock test, Contest, Pub quiz, Basic quiz) when creating a quiz or later; the type writes its settings, the quiz remembers it and shows where it deviates.

**Architecture:** A new port `quiz_type` (contract `QuizTypePlugin`) with a plugin `app/plugins/quiz_types/` holding the six definitions. A domain service `app/domain/quiz_types.py` previews and applies a type (one transaction, clashes adjusted or refused, disabled modules skipped) and lists deviations; the clash rules of the settings form move to `app/domain/setting_rules.py` so the form and the service share them. `Quiz.quiz_type` remembers the type. The API adds a disclosure on the new-quiz form, a type bar and marks on the settings page, and a confirmation page.

**Tech Stack:** Django, Jinja2, HTMX (none needed here), pytest, Babel.

**Spec:** `docs/superpowers/specs/2026-11-12-quiz-types-design.md`

## Global Constraints

- Values per type exactly as the table in the spec; Basic removes every quiz setting override and nothing else (not branding, not `anonymous_label`).
- A type writes ordinary quiz overrides via `settings.set_override`; the quiz stores only the type id (`Quiz.quiz_type`, empty = no type).
- Deviation = a key the type sets whose `settings.resolve(key, quiz)` differs from the type's value; for Basic every key with a quiz override.
- Change type: keys of the old type (its current definition) that the new one does not set go back to the global value (override deleted).
- Clash adjustable on the quiz (`answers_visibility` vs profile → `admins`; duration column/sort without `detailed` → `off`/`submitted`) is adjusted and listed; any other clash, including with a planned or open run (after-each reveal vs visible scoreboard or rewards on a run, AC-18), refuses the whole type with the settings form's message; nothing is written.
- A key whose owning module is disabled (`registry.is_enabled`) is skipped and listed.
- Overview warns when the quiz has a planned or open run (navigation, page size, reveal, shuffle, sources are read live) and when content does not go with the values (`requirements` unmet, e.g. a photo question with `after_each`).
- Audit: `quiz.type_applied` (details `{"type": id}`) and `quiz.type_removed`, plus the existing per-setting `setting.changed`; no personal data.
- Duplicating a quiz copies `quiz_type` and all its `AppSetting` rows with `quiz=` the source; branding is not copied.
- Every admin POST has `{{ csrf_input }}`; no inline script or style; everything works without JavaScript.
- Admin strings cs and en (`make messages`, `msgstr` filled); the plugin's catalogue cs and uk.
- New AC-171, ADR-0062 (the `quiz_type` port), README range `AC-01…AC-171`; migration `0023`.

## Review Focus

- Contest → Practice on a quiz with an open run whose scoreboard is visible: refused (409), no override and no `quiz_type` changed.
- Global `answers_visibility=public`: applying Practice (`data_profile=score`) sets the quiz's `answers_visibility` to `admins` and the overview lists it.
- Rewards module disabled on the Modules page: Contest skips `reward_source` and `winner_contact`, lists them, applies the rest.
- The type plugin disabled while quizzes remember a type: the settings page shows the type's name without actions and no 500; the new-quiz form offers no types.
- Two admins: one opens the overview, the other changes a setting, the first confirms: the POST recomputes from the current state (the overview is never trusted).

---

### Task 1: The `quiz_type` port and the plugin with six types

**Files:**
- Modify: `app/contracts/__init__.py` (Protocol + `PORTS`), `docs/plugin-api.md`
- Create: `app/plugins/quiz_types/{__init__,manifest,apps,plugin}.py`, `app/plugins/quiz_types/locale/…`
- Modify: `pyproject.toml` (entry point `"quiz_types.basic" = "app.plugins.quiz_types.manifest:MANIFEST"`), `tools/messages.py` (`ROOTS`)
- Create: `tests/contracts/quiz_type.py`, `tests/contracts/test_quiz_types.py`
- Create: `docs/_architecture/plugins/quiz-types.md`, `docs/_architecture/adr/0062-quiz-type-port.md` (+ `adr/README.md` row)

**Interfaces — Produces:**
```python
@runtime_checkable
class QuizTypePlugin(Protocol):
    """A named bundle of quiz settings (ADR-0062). Definitions only; applying is the domain's."""
    id: str
    version: str
    order: int            # position in lists, ascending
    resets_all: bool      # True only for Basic: removes every quiz override
    def label(self) -> str: ...
    def description(self) -> str: ...
    def values(self) -> Mapping[str, str]: ...   # setting key -> value; {} for Basic
```
`PORTS["quiz_type"] = QuizTypePlugin`. The plugin registers six objects, keys `practice`, `final_test`, `mock_test`, `contest`, `pub_quiz`, `basic`, owner `"quiz_types.basic"`. Manifest: `kind: plugin`, `provides: ["quiz_type"]`, `settings: []`, not `always_on`.

- [ ] **Step 1: Contract suite** `tests/contracts/quiz_type.py` class `QuizTypeContract` (attribute `plugins: list`): `test_satisfies_protocol`; `test_label_and_description_not_empty`; `test_every_key_is_a_quiz_setting` (`key in settings.CATALOGUE` and `"quiz" in CATALOGUE[key].scopes`); `test_every_value_is_offered` (`value in CATALOGUE[key].choices`); `test_values_do_not_clash` (`not settings.is_flow_conflict(nav, moment)` with the type's values falling back to defaults, and `not settings.is_visibility_conflict(...)`); `test_reset_type_has_no_values` (`resets_all` ⇒ `values() == {}`); `test_orders_are_unique`. `tests/contracts/test_quiz_types.py` runs it on the six plugin objects and asserts the spec table exactly, e.g.:
```python
def test_final_test_values():
    assert by_id("final_test").values() == {
        "navigation_mode": "step_no_back", "reveal_moment": "never",
        "shuffle_questions": "on", "shuffle_options": "on", "attempt_limit": "30",
        "repeat_attempts": "forbid", "ask_name": "required", "ask_when": "start",
        "ask_email": "off", "duplicate_names": "allow", "scoreboard_visibility": "hidden",
        "official_attempt": "first", "data_profile": "answers", "show_sources": "off",
    }
```
(one such test per type, values from the spec table; `–` cells are absent keys). Labels cs/en from the spec's names; Contest's description says the prize is added on the Rewards tab; Pub quiz's says one phone per team with the team name as nickname.
- [ ] **Step 2: Run** `uv run pytest tests/contracts/test_quiz_types.py -q` — Expected: FAIL (import error).
- [ ] **Step 3: Implement** the Protocol, `PORTS`, the plugin (one frozen dataclass `QuizType` in `plugin.py` satisfying the Protocol; labels via the module's `gettext`), manifest, `apps.ready()` registering each type; entry point; `make setup`.
- [ ] **Step 4: Run** `uv run pytest tests/contracts tests/test_wiring.py -q` — Expected: PASS (wiring may demand the doc file and `ROOTS`: add `docs/_architecture/plugins/quiz-types.md` with the table and `ROOTS` entry, then `make messages`, fill cs and uk).
- [ ] **Step 5: ADR-0062** (status accepted: user approved the design 2026-11-12): context, decision (port `quiz_type`, definitions only, domain applies), consequences; `docs/plugin-api.md` section for `QuizTypePlugin`.
- [ ] **Step 6: Commit** `feat(quiz-types): quiz_type port and plugin with six types (ADR-0062)` including the spec, this plan and the TECH_DEBT entries TD-094…TD-101.

### Task 2: Clash rules as domain rules

**Files:**
- Create: `app/domain/setting_rules.py`; Test: `tests/domain/test_setting_rules.py`
- Modify: `app/api/admin_forms.py:162-291` (the `_refuse_*` helpers call the domain), existing tests stay green.

**Interfaces — Produces:**
```python
@dataclass(frozen=True)
class Clash:
    reason: str      # FLOW, VISIBILITY, STATELESS, RESULT_STATELESS, RESULT_AFTER_EACH,
                     # NEEDS_TIMES, RUN_BOARD, RUN_REWARDS
    key: str         # the setting the message attaches to
    detail: str | None = None  # the participant key for STATELESS, data_policy.PHOTO_QUESTION
ADJUSTABLE: dict[str, dict[str, str]]  # reason -> {key: value that ends it}
#   VISIBILITY  -> {"answers_visibility": "admins"}
#   NEEDS_TIMES -> {"scoreboard_show_duration": "off", "scoreboard_second_sort": "submitted"}
def clashes(values: Mapping[str, str], quiz: Quiz | None) -> list[Clash]:
    """`values` are resolved values (missing keys resolve globally); `quiz` None = the global form."""
```
- [ ] **Step 1: Failing tests** in `tests/domain/test_setting_rules.py`, one per reason, each building `values` and asserting `[c.reason for c in clashes(values, quiz)]`: pages + after_each → `FLOW`; score + public → `VISIBILITY`; none + ask_name required → `STATELESS` with `detail="ask_name"`; live board + after_each → `RESULT_AFTER_EACH`; duration on + score → `NEEDS_TIMES`; after_each on a quiz with an open run whose board is `live` → `RUN_BOARD`; after_each on a quiz with a scheduled run with a reward rule → `RUN_REWARDS`; consistent values → `[]`.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_setting_rules.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** by moving the logic of `_refuse_*` and `_visible_board_on_a_run`/`_rewards_on_a_run` into `clashes`; the form helpers become one `_refuse_clashes(form)` that builds `values` from `cleaned_data` (empty → `settings.resolve(key)`, as today) and maps each `Clash` to the existing messages and fields.
- [ ] **Step 4: Run** `uv run pytest tests/domain tests/api -q` — Expected: PASS (the form behaviour is unchanged).
- [ ] **Step 5: Commit** `refactor(settings): clash rules of the settings form as domain rules`

### Task 3: Applying a type (domain) and duplicate

**Files:**
- Modify: `app/domain/models.py` (`Quiz.quiz_type = models.CharField(max_length=64, blank=True, default="")`), Create: `app/domain/migrations/0023_quiz_type.py`
- Create: `app/domain/quiz_types.py`; Test: `tests/domain/test_quiz_types.py`
- Modify: `app/domain/authoring.py` (`duplicate_quiz`); Test: `tests/domain/test_authoring.py`

**Interfaces — Consumes:** Task 1 port, Task 2 `clashes`/`ADJUSTABLE`. **Produces:**
```python
class TypeRefused(Exception):  # .clashes: list[Clash]
class UnknownType(Exception)
@dataclass(frozen=True)
class Change: key: str; current: str; new: str | None   # None = back to the global value
@dataclass(frozen=True)
class Preview:
    type_id: str
    changes: list[Change]        # values the type writes or removes, only where they differ
    adjusted: list[Change]       # clash fixes on other settings
    skipped: list[str]           # keys of disabled modules
    refused: list[Clash]         # non-adjustable clashes; non-empty = cannot apply
    live_run: bool               # a planned or open run exists
    content: list[str]           # requirement keys the quiz content does not meet
def available() -> list[QuizTypePlugin]          # enabled, by `order`
def get(type_id: str) -> QuizTypePlugin | None   # include_disabled, for the label
def preview(quiz: Quiz, type_id: str) -> Preview
def apply(quiz: Quiz, type_id: str, *, admin_id: str) -> Preview   # raises TypeRefused, UnknownType
def remove(quiz: Quiz, *, admin_id: str) -> None
def deviations(quiz: Quiz) -> dict[str, str | None]  # key -> the type's value (None = global, Basic)
```
- [ ] **Step 1: Failing tests** (`tests/domain/test_quiz_types.py`): apply Final test on a fresh quiz writes the overrides of its table and `quiz.quiz_type == "final_test"`, one `quiz.type_applied` audit with `details == {"type": "final_test"}`; deviations empty, then `set_override(attempt_limit, "45")` → `deviations == {"attempt_limit": "30"}`; Contest then Practice removes `reward_source`, `winner_contact`, `duplicate_names`, `official_attempt`, `ask_when` overrides and `preview` lists them with `new=None`; global `answers_visibility=public` + Practice → override `answers_visibility=admins` in `adjusted`; open run with `scoreboard_visibility=live` in `results_json` + Practice → `TypeRefused` with `RUN_BOARD`, nothing written, `quiz_type` unchanged; `PluginInstallation(pk="rewards.threshold", enabled=False)` + Contest → `skipped == ["reward_source", "winner_contact"]` and no override for them; Basic removes every override (other keys too), keeps `anonymous_label`, `deviations` lists remaining overrides with `None`; `remove` keeps overrides and clears `quiz_type`; photo question + Practice → `content` non-empty, apply succeeds; `live_run` true with a scheduled run; unknown id → `UnknownType`; apply recomputes (a change between `preview` and `apply` is respected). Duplicate test: source with `quiz_type="contest"` and two overrides → copy has the same type and both overrides, branding row not copied.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_quiz_types.py tests/domain/test_authoring.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement**: target = (overrides minus old type's keys not in new) + new values (Basic: no overrides); skip keys owned by a disabled module (owner = the manifest in `django.conf.settings.KVZ_MODULES` whose `settings` declare the key; core keys have none); resolve target, run `clashes(resolved, quiz)`, apply `ADJUSTABLE` fixes (re-check once), refuse the rest; write in `transaction.atomic()` via `settings.set_override` (only changed keys), save `quiz_type`, audit. `content` from the existing requirements check (`app/domain/requirements.py`) with the target values. Duplicate copies `quiz_type` and the source's `AppSetting` rows in its transaction.
- [ ] **Step 4: Run** `uv run pytest tests/domain -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(quiz-types): apply, change and remove a type; duplicate copies type and settings`

### Task 4: Admin pages

**Files:**
- Modify: `app/api/admin_forms.py` (`QuizForm.quiz_type` optional `ChoiceField`, choices `[("", _("No type")), *available]`), `app/api/admin_quizzes.py` (`quiz_new` applies the type after create; `settings_page` adds `quiz_type`, `type_marks`), `app/api/admin_urls.py`
- Create: `app/api/admin_quiz_types.py` (views), `app/api/jinja2/admin/_quiz_type_bar.html`, `app/api/jinja2/admin/quiz_type_confirm.html`
- Modify: `app/api/jinja2/admin/quiz_form.html` (`<details class="quiz-type-choice">` with `<summary>{{ _("Quiz type") }}</summary>`, radios with label + description), `quiz_settings.html` (include the bar above `#copy`), `_setting_row.html` (optional `mark` argument: `<small class="type-mark">▲ {{ _("type: %(value)s") }}</small>`), `_setting_groups.html` (passes `type_marks.get(field.name)`), `app/plugins/theme_default/assets/theme.css` (`.quiz-type-bar`, `.type-mark`, `.quiz-type-choice`)
- Test: `tests/api/test_admin_quiz_types.py`, `tests/api/test_request_limits.py` (if a new argument)

**Interfaces — Consumes:** Task 3. **Produces:** routes `quizzes/<uuid:quiz_id>/type` name `admin_quiz_type` (GET `?type=<id>` → overview; POST `type`, `confirm=1` → apply, redirect to settings; refused → overview with messages, 409), `quizzes/<uuid:quiz_id>/type/remove` name `admin_quiz_type_remove` (POST). Both behind `admin_required` and `not_archived`.

- [ ] **Step 1: Failing tests**: new-quiz page has a closed `<details>` with six types and "No type" checked; POST with `quiz_type=practice` creates the quiz with Practice's overrides, without it as today; settings page without a type shows "Choose a type" form, with one shows the bar "Final test · 2 deviations" and `▲` marks on exactly the deviating fields (also in Basic view); GET overview lists changes, removals, adjusted, skipped, the live-run warning and the content warning in text; POST without `confirm=1` shows the overview, with it applies; refused clash → 409 with the form's message and nothing changed; Apply again and Change type use the same route; Remove keeps values; archived quiz → 409; plugin disabled → bar shows the label without actions, new-quiz form has no disclosure; every form has CSRF; no `style=`/inline `<script>`.
- [ ] **Step 2: Run** `uv run pytest tests/api/test_admin_quiz_types.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement**; messages for refused clashes reuse `admin_forms` message helpers; change labels come from `settings.CATALOGUE[key].label` and `value_labels` ("global value (now: X)" for `None`).
- [ ] **Step 4: Run** `uv run pytest tests/api tests/test_wiring.py -q` then `make messages` (cs filled) and `uv run pytest tests/test_translations.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(quiz-types): choose a type on the new quiz and settings pages, deviations and confirmation`

### Task 5: Documentation, checks, browser

- [ ] **Step 1:** AC-171 in `acceptance-criteria.md` (choose on create and later, remembered, deviations with marks, change with overview and back to global, clash adjusted or refused, disabled modules skipped, live-run and content warnings, duplicate copies type and settings, audit without personal data), README range; `docs/_architecture/modules/api-ui.md` (settings page bar, new-quiz disclosure), `docs/_architecture/modules/domain.md` (`quiz_types.py`, `setting_rules.py`), `docs/_architecture/data-model.md` (`Quiz.quiz_type`), `app/domain/CLAUDE.md`, `app/api/CLAUDE.md`, `app/plugins/CLAUDE.md` line; project `CLAUDE.md` status sentence mentions quiz types.
- [ ] **Step 2: Run** `uv run pytest tests/test_docs.py -q` then `make quality` — Expected: PASS, exit 0.
- [ ] **Step 3: Browser check** (`kvizotron-browser-walkthrough`) on a throwaway instance: new quiz with Pub quiz via the disclosure; settings bar and marks after changing the time limit; change to Practice with the overview; refused change with an open run with a live scoreboard; 1280 light cs, 390 dark uk; keyboard only for create → apply.
- [ ] **Step 4: Commit** `docs: quiz types (AC-171, ADR-0062)`

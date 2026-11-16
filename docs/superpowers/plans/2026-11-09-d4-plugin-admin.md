# D4 Plugin admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin page lists every module, switches plugins with clear refusals, shows each module's settings and where a value differs from the global one, and disabling a plugin no longer breaks any page.

**Architecture:** The kernel gains one non-raising answer to "why can't this module change state" (`lifecycle.blockers`), which `set_enabled` and the page share. Domain and API add reasons through the existing usage checks. A domain module reads the overrides; `app/api/admin_plugins.py` renders both pages.

**Tech Stack:** Django, Jinja2, Pydantic manifests, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-d4-plugin-admin-design.md`

## Global Constraints

- `app/kernel` must not import `app/domain`, `app/api`, `app/plugins` or `app/providers` (`tests/test_layers.py`).
- UI texts in cs, en and uk; "běh", not "kolo". After adding texts run `make messages`; `.po` and `.mo` are committed.
- Docs in English, ids (`AC`, `ADR`, `TD`) stable. Deferred items only through `make tech-debt-create title="…"`.
- No new setting, no new table, no new dependency, no migration.
- Existing tests are not deleted or weakened. Every behaviour change starts from a failing test.
- `Manifest` keeps `api_compatibility` `>=1.0,<2.0`: new manifest fields are optional.
- Never print `KVZ_SECRET_KEY`. In `kvizotron-browser` verify on a new quiz, and enable again any plugin you disabled.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never stage `app/api/assets/{apple-touch-icon.png,favicon-32.png,logo.svg}` or `tests/api/test_public_layout.py`: they hold the user's uncommitted logo work, and `test_logo_is_the_designers_drawing` fails in this tree because of it. Verify with `make quality` in a clean checkout, or name that one failure when reporting.

## Review Focus

1. A plugin disabled and enabled again: a draft holding its questions works exactly as before (Task 2).
2. Disabling every question type: the quiz editor still opens, with an empty add menu (Task 2).
3. Double click or two admins on "Disable": one state change, one audit event, no error (Task 4).
4. A POST naming a provider, an unknown module or a locked plugin answers a refusal or 404, never 500 (Task 4).
5. A scheduled run whose quiz holds the type blocks disabling although the run has no revision rows yet (Task 1).

---

### Task 1: Kernel refusals, locks and module names

**Files:**
- Modify: `app/kernel/lifecycle.py`, `app/kernel/manifest.py`, `app/kernel/management/commands/modules.py`, `app/domain/usage.py`, `app/api/rendering.py` (`last_theme_usage`), all 17 `manifest.py` in `app/plugins` and `app/providers`
- Modify: `tools/messages.py` only if it does not scan `app/kernel` (read it first); `docs/plugin-api.md`, `app/kernel/CLAUDE.md`
- Test: `tests/kernel/test_lifecycle.py`, `tests/domain/test_usage.py`, `tests/integration/test_startup_verification.py`, `tests/test_wiring.py` is not edited

**Interfaces:**
- Produces, in `app/kernel/lifecycle.py`:
  - `@dataclass(frozen=True) class Blocker: kind: Literal["provider", "locked", "in_use", "dependency"]; text: str; target: tuple[str, str] | None = None`. `target` is opaque to the kernel; used values are `("run", str(run.pk))` and `("quiz", str(quiz.pk))`.
  - `def blockers(module_id: str, enabled: bool) -> list[Blocker]`: why the module cannot move to `enabled`; empty when it can or when it is already there. Raises `UnknownModule` for an unknown id.
  - `class ModuleLocked(LifecycleError)`.
  - `register_usage_check(check: Callable[[str], list[Blocker]])` (signature change).
- Produces, in `app/kernel/manifest.py`: `always_on: bool = False`, `name: str | None = None`, `description: str | None = None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/kernel/test_lifecycle.py
def test_blockers_are_empty_for_a_free_plugin(db):
    assert lifecycle.blockers("plug.a", False) == []

def test_a_provider_has_a_provider_blocker(db):
    assert [b.kind for b in lifecycle.blockers("prov.auth", False)] == ["provider"]

def test_always_on_module_refuses_with_module_locked(db, always_on_module):
    with pytest.raises(lifecycle.ModuleLocked):
        lifecycle.set_enabled(always_on_module, False, **CLI)

def test_an_already_disabled_always_on_module_can_be_enabled(db, always_on_module):
    PluginInstallation.objects.update_or_create(pk=always_on_module, defaults={"enabled": False})
    assert lifecycle.blockers(always_on_module, True) == []
```

```python
# tests/domain/test_usage.py
@pytest.mark.parametrize("module", ["flow.basic", "participants.basic", "results.local", "scoring.basic"])
def test_essential_plugin_is_locked(module):
    with pytest.raises(lifecycle.ModuleLocked):
        set_enabled(module, False)

def test_a_scheduled_run_blocks_disabling_its_question_type():
    run = planned_run()  # a SCHEDULED run of a published quiz; no revision rows
    assert any(b.kind == "in_use" and b.target == ("run", str(run.pk))
               for b in lifecycle.blockers("question.choice", False))

def test_reason_follows_the_active_language():
    open_quiz_run()
    with translation.override("cs"):
        text = lifecycle.blockers("question.choice", False)[0].text
    assert "běh" in text

def test_every_module_in_the_repository_has_a_name_and_description():
    assert all(m.name and m.description for m in settings.KVZ_MODULES)
```

Add `test_modules_disable_flow_is_refused` to `tests/integration/test_startup_verification.py`, in the style of the existing `retention.local` refusal there. Build `planned_run()` from how `tests/domain` plans a run; `always_on_module` is a fake manifest in the style of `plug.a`.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/kernel/test_lifecycle.py tests/domain/test_usage.py -q`
Expected: FAIL, `lifecycle.blockers` and `ModuleLocked` do not exist.

- [ ] **Step 3: Implement**

`blockers` collects in this order: provider, in-use reasons, `always_on` when disabling, dependency reasons. Blocker texts use `django.utils.translation.gettext`, evaluated when called, so they follow the active language.

`set_enabled` keeps its early return, computes `blockers` inside `translation.override("en")` so exceptions and `manage.py` stay in English, and raises for the first blocker: `provider` → `NotToggleable`, `in_use` → `ModuleInUse`, `locked` → `ModuleLocked`, `dependency` → `DependencyDisabled`. Keep the existing message wording, so tests matching `"run 1 of quiz kviz"` and `"kviz"` still pass. In-use goes before locked because `test_plugin_used_by_open_run_cannot_be_disabled[scoring.basic]` expects `ModuleInUse`.

`question_type_usage` covers `Status.OPEN` and `Status.SCHEDULED`. A scheduled run may have no `revision_rows`; read `run.current_revision.snapshot_json` for it. `missing_plugin_problems` keeps its current behaviour: keep a separate open-only iterator for it, since a missing module on a planned run must not stop the start. Reasons carry `target=("run", str(run.pk))`.

Set `always_on: True` on `flow.basic`, `participants.basic`, `results.local`, `scoring.basic`. Give all 17 manifests a `name` and one-line `description` marked with the module's `_()`. Example: `question.image_answer` is "Photo" / "Participants answer by uploading a photo that an admin grades."

`manage.py modules list` is unchanged.

- [ ] **Step 4: Run tests and catalogues**

Run: `make messages && uv run pytest tests/kernel tests/domain/test_usage.py tests/api/test_theme_guard.py tests/integration/test_startup_verification.py tests/contracts tests/test_layers.py tests/test_translations.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app tools docs/plugin-api.md tests/kernel tests/domain/test_usage.py tests/integration/test_startup_verification.py
git reset -q app/api/assets/apple-touch-icon.png app/api/assets/favicon-32.png app/api/assets/logo.svg
git commit -m "feat(plugins): reasons for refusing a change of module state, essential plugins locked"
```

---

### Task 2: Pages survive a disabled or missing plugin

**Files:**
- Modify: `app/domain/run_stats.py:91`, `app/domain/preview.py:122-125`, `app/api/admin_preview.py:213`, `app/domain/rewards.py`, `app/domain/draws.py`, `app/api/admin_rewards.py`, `app/api/admin_forms.py` (reward rule `kind` choices), `app/domain/walkthrough.py`, `app/api/public.py` (only where TD-017 needs it), `app/api/admin_import.py:209` if it can reach a disabled type
- Test: create `tests/api/test_disabled_plugin.py`, and extend `tests/domain/test_usage.py`

**Interfaces:**
- Consumes: `lifecycle.set_enabled`; `registry.ModuleDisabled`, `registry.UnknownPort`.
- Produces: `rewards.RuleInvalid("plugin_disabled")` and `draws.DrawRefused("plugin_disabled")`, with messages in the form's existing error tables.

- [ ] **Step 1: Write the failing tests** (`tests/api/test_disabled_plugin.py`, AC-126 and AC-127)

```python
def test_disabled_type_is_not_offered_for_a_new_question(admin_client): ...
    # disable question.number; GET admin_quiz_edit; "type=number" not in the page;
    # GET admin_question_new?type=number is 404

def test_disabled_type_is_not_offered_or_saved_in_a_bank(admin_client): ...
    # disable question.number; the bank's add menu has no number; a POST of one is refused

def test_import_row_of_a_disabled_type_is_refused_with_its_row_message(admin_client): ...
    # disable question.number; upload a CSV with one number row; response < 500, names the row

def test_draft_with_a_disabled_type_opens_and_publication_refuses(admin_client): ...
    # a draft with a number question; disable; quiz edit is 200, the question is listed;
    # publish answers the problems page with status 200 or 400, naming the question

def test_preview_of_a_draft_with_a_disabled_type_is_refused_not_an_error(admin_client): ...
    # disable; start preview; response < 500 and shows the question as unusable

def test_reenabled_type_leaves_the_draft_as_it_was(admin_client): ...
    # disable, enable; quiz edit shows it; publication succeeds

def test_editor_opens_with_every_question_type_disabled(admin_client): ...
    # closed runs only; disable all five; quiz edit is 200

@pytest.mark.parametrize("name", ["statistics", "comparison", "grading", "attempts", "export"])
def test_page_of_a_past_run_answers_with_its_type_disabled(admin_client, name): ...
    # closed run, disable its type, each page is 200

def test_public_pages_of_a_past_run_answer_with_its_type_disabled(client): ...
    # scoreboard, private result link, walkthrough are 200

def test_reward_kinds_needing_a_disabled_plugin_are_not_offered(admin_client): ...
    # rewards.threshold off: "threshold" absent from the kind select on quiz rewards;
    # POST of a threshold rule shows the refusal; a draw rule with a minimum is refused too

def test_draw_is_refused_with_a_message_when_the_plugin_is_off(admin_client): ...
    # drawings.manual off, a closed run's rule on an archived run or one created before
    # disabling via the model; rule page is 200 and states the refusal; history still shows

def test_walkthrough_of_an_uninstalled_type_leaves_the_question_out(client): ...
    # TD-017: registry.get raises UnknownPort for the type (monkeypatch); page is 200
```

Each `...` comment is that test's arrange and assertions. Use `tests.domain.helpers` and `tests.support.client.FormClient`, as `tests/api/test_admin_retention.py` does. Note a live reward rule blocks disabling, so a rule must exist only on an archived run for the last draw test.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/api/test_disabled_plugin.py -q`
Expected: several FAIL; statistics and preview raise `ModuleDisabled`.

- [ ] **Step 3: Implement**

- `run_stats.question_max`: `include_disabled=True`.
- `preview.unusable` catches `LookupError`, as `_question_problems` does; `admin_preview` catches `LookupError` where it catches `UnknownPort`. Check `preview.py:148` too.
- Rewards: `_kind_labels` and the form's `kind` choices leave out `THRESHOLD` when `reward`/`threshold` is off and `DRAW` when `drawing`/`manual` is off, using `registry.keys`. `save_rule` raises `RuleInvalid("plugin_disabled")` for a `THRESHOLD`, or a `DRAW` with `min_unit`, when the reward port is off, and for any `DRAW` when the drawing port is off. A rule being edited keeps its own kind in the choices, so the page opens.
- Draws: `draws._ensure_draw_rule` raises `DrawRefused("plugin_disabled")` when the port is off, so `refusal` reports it read-only and `draw` refuses. `_eligible` and `standing` on an existing history must not call a disabled port.
- `app/domain/rewards.py:431` `_reward()` and `draws._reward()` read with `include_disabled=True` for already stored rules, so the rewards pages of a past run keep showing them.
- Import and banks: a row or bank question of a disabled type is refused through `question_import`'s and `banks`' existing messages, not by `ModuleDisabled` reaching the page. Catch `LookupError` around `_plugin` in `question_import`, `admin_import._preview_rows` and `banks.py:113`.
- TD-017: `walkthrough._plugin` callers leave the question out on `UnknownPort`, as `_own_answers` does.

- [ ] **Step 4: Run them to verify they pass**

Run: `make messages && uv run pytest tests/api/test_disabled_plugin.py tests/domain tests/test_translations.py -q`
Expected: PASS.

- [ ] **Step 5: Resolve TD-017 and commit**

```bash
make tech-debt-resolve id=TD-017
git add app docs/_architecture tests/api/test_disabled_plugin.py
git reset -q app/api/assets/apple-touch-icon.png app/api/assets/favicon-32.png app/api/assets/logo.svg
git commit -m "fix(plugins): pages answer with a disabled or missing plugin"
```

---

### Task 3: Where a value differs from the global one

**Files:**
- Create: `app/domain/plugin_overview.py`
- Test: create `tests/domain/test_plugin_overview.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Difference: quiz: Quiz; value: str; question_id: str | None; question_no: int | None`
  - `@dataclass(frozen=True) class SettingOverview: key: str; global_value: str; differences: list[Difference]; total: int`
  - `LIMIT = 50`
  - `def overview(manifest: Manifest) -> list[SettingOverview]`, one per `manifest.settings` in manifest order.

- [ ] **Step 1: Write the failing tests** (AC-125)

```python
KEY = "photo_visibility"  # scopes include global, quiz and question

def only(manifest_id): ...  # the SettingOverview of KEY for that module

def test_quiz_override_that_differs_is_listed():
    quiz = published_quiz()
    settings.set_override(KEY, quiz, "admins", admin_id=ADMIN_ID)
    row = only("question.image_answer")
    assert [(d.quiz, d.value, d.question_no) for d in row.differences] == [(quiz, "admins", None)]

def test_override_equal_to_global_is_not_listed(): ...
def test_question_value_is_listed_with_its_number(): ...
def test_question_value_equal_to_global_is_not_listed_even_if_quiz_differs(): ...
def test_draft_wins_over_the_published_revision(): ...
    # published question has a differing value, the draft has removed it: not listed
def test_published_revision_is_read_when_there_is_no_draft(): ...
def test_archived_quiz_is_left_out(): ...
def test_a_value_no_longer_offered_counts_as_none(): ...
def test_setting_without_question_scope_has_no_question_rows(): ...
    # color_palette: a question "settings" entry for it is ignored
def test_unset_global_counts_as_the_default(): ...
def test_list_is_cut_to_the_limit_and_total_is_kept(): ...
    # LIMIT + 1 quizzes with overrides, monkeypatch LIMIT to 2 for speed
def test_module_without_settings_gives_an_empty_list(): ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/domain/test_plugin_overview.py -q`
Expected: FAIL, module does not exist.

- [ ] **Step 3: Implement `overview`**

Global value: `settings.resolve(key)`. Quiz rows from `AppSetting` with `quiz__isnull=False`, `quiz__archived_at__isnull=True`, value offered by `CATALOGUE[key].choices`; only when `"quiz"` is in the setting's scopes. Question rows only when `"question"` is in scopes: for each non-archived quiz take its `DRAFT` revision, else `authoring.latest_published`; walk `snapshot_json["questions"]`, number from 1, use `settings.question_value`. Bank questions and draw rows are not read. Read each quiz's revision once per call, not once per setting. Order: quizzes by `created_at`, a quiz's own row before its questions.

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest tests/domain/test_plugin_overview.py tests/test_layers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/domain/plugin_overview.py tests/domain/test_plugin_overview.py
git commit -m "feat(plugins): find where a module's setting differs from the global value"
```

---

### Task 4: Admin pages

**Files:**
- Create: `app/api/admin_plugins.py`, `app/api/jinja2/admin/plugins.html`, `app/api/jinja2/admin/plugin.html`
- Modify: `app/api/admin_urls.py`, `app/api/jinja2/admin/base.html`, `app/plugins/theme_default/assets/theme.css` only if existing table and status classes do not fit
- Test: create `tests/api/test_admin_plugins.py`

**Interfaces:**
- Consumes: `lifecycle.blockers`, `lifecycle.set_enabled`, `lifecycle.LifecycleError`, `registry.is_enabled`, `plugin_overview.overview`, `settings.CATALOGUE`.
- Produces routes: `plugins` → `admin_plugins`; `plugins/<str:module_id>` → `admin_plugin`; `plugins/<str:module_id>/state` POST → `admin_plugin_state`, field `enabled` = `on`/`off`.

- [ ] **Step 1: Write the failing tests** (AC-120, 121, 122, 123, 124)

```python
def test_list_shows_all_modules_and_a_provider_has_no_switch(admin_client):
    body = text(admin_client.get(reverse("admin_plugins")))
    for manifest in settings.KVZ_MODULES:
        assert manifest.version in body
    assert reverse("admin_plugin_state", args=["auth.local"]) not in body

def test_pages_require_login(client):
    for name, args in (("admin_plugins", []), ("admin_plugin", ["question.number"])):
        assert client.get(reverse(name, args=args)).status_code == 302

def test_disable_and_enable_apply_at_once_and_are_audited(admin_client): ...
    # POST off: is_enabled False, AuditEvent plugin.disabled with the admin id; POST on: True

def test_state_needs_csrf(enforcing_client): ...
    # as test_the_erasure_search_passes_a_real_csrf_check does

def test_second_disable_changes_nothing(admin_client): ...
    # two POSTs answer redirect; exactly one plugin.disabled event

@pytest.mark.parametrize("module", ["flow.basic", "participants.basic", "results.local", "scoring.basic"])
def test_locked_plugin_has_no_switch_and_a_post_is_refused(admin_client, module): ...

def test_post_for_a_provider_is_refused_not_an_error(admin_client): ...
def test_unknown_module_is_404(admin_client): ...  # GET and POST
def test_invalid_state_value_is_400(admin_client): ...

def test_in_use_detail_lists_the_run_with_a_link_in_the_admin_language(admin_client): ...
    # open run; detail in cs shows the reason and reverse("admin_run", args=[run.pk])

def test_refused_post_shows_the_reason_on_the_detail_page(admin_client): ...
    # status 409, reason in the body, is_enabled unchanged

def test_detail_lists_settings_with_global_value_and_links(admin_client): ...
    # question.image_answer: label, global value label, reverse("admin_settings")

def test_different_elsewhere_links_to_quiz_settings_and_question(admin_client): ...
    # reverse("admin_quiz_settings", args=[quiz.id]),
    # reverse("admin_question_edit", args=[quiz.id, question_id])

def test_module_without_settings_says_so(admin_client): ...
def test_detail_shows_what_it_requires_and_who_depends_on_it(admin_client): ...
    # question.image_answer requires media_storage; media.local lists it as dependent
def test_long_list_shows_the_total(admin_client, monkeypatch): ...
```

Build `admin_client` as `tests/api/test_admin_retention.py` does.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/api/test_admin_plugins.py -q`
Expected: FAIL, `NoReverseMatch`.

- [ ] **Step 3: Implement the views and templates**

`plugins_page`, `plugin_page`, `plugin_state`, all `@admin_required`, section `plugins` in navigation, after "Admins", label `_("Modules")`. Module name: `gettext(manifest.name)` or the id. Rows: plugins first, then providers. `blockers(id, not currently_enabled)` decides the row: empty → button; else the first blocker's text. The detail lists all blockers and maps `target` with `{"run": "admin_run", ...}`; a `quiz` target links to `admin_quiz_edit`.

`plugin_state`: unknown id → 404; `enabled` not `on`/`off` → 400. Call `set_enabled(..., actor_type="admin", actor_id=str(request.user.pk))`; on `LifecycleError` re-render the detail with status 409, which recomputes the reasons in the admin's language; success redirects to the list.

Setting rows use `settings.CATALOGUE[key].label` and `.value_labels`. Global value links to `admin_settings`; a quiz row to `admin_quiz_settings`, a question row to `admin_question_edit`, shown as quiz title and "question N" via `admin_workspace.quiz_title`. A global-only setting has no "Different elsewhere". Show "showing first 50 of N" when `total > LIMIT`.

Tables must not overflow at 390 px: reuse a wrapping pattern already in `theme.css`, not a horizontal scroll that hides the state.

- [ ] **Step 4: Run them to verify they pass**

Run: `make messages && uv run pytest tests/api/test_admin_plugins.py tests/test_wiring.py tests/test_translations.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api tests/api/test_admin_plugins.py
git reset -q app/api/assets/apple-touch-icon.png app/api/assets/favicon-32.png app/api/assets/logo.svg
git commit -m "feat(plugins): modules page and detail in the administration"
```

---

### Task 5: Documents of the milestone

**Files:**
- Create: `docs/_architecture/adr/0057-plugin-admin-locks-and-no-configuration-table.md`
- Modify: `docs/_architecture/adr/README.md`, `docs/_architecture/roadmap.md`, `docs/_architecture/acceptance-criteria.md`, `docs/_architecture/modules/kernel.md`, `docs/_architecture/modules/api-ui.md`, `docs/_architecture/modules/domain.md`, `docs/_architecture/data-model.md`, `docs/_architecture/adr/0038-revision-switch-policy-and-settings.md`, `app/domain/settings.py` (docstring), `CLAUDE.md`, `app/api/CLAUDE.md`, `app/domain/CLAUDE.md`, `app/kernel/CLAUDE.md`, `.claude/skills/kvizotron-check-integration/flows.md`
- Test: `tests/test_docs.py`

- [ ] **Step 1: Add AC-120 to AC-127** with the texts of the spec's Verification section, Stage `D`; each test named in Tasks 1 to 4 that proves one carries its id in the docstring, as earlier AC tests do. Run `uv run pytest tests/test_docs.py -q`; it must fail until the tests name them, then pass.

- [ ] **Step 2: Write ADR-0057** in MADR 4, `status: accepted`: reasons as `Blocker`, `always_on` over a list in the kernel, `name`/`description` optional, and no `plugin_configuration` until a module needs one.

- [ ] **Step 3: Update the rest.** Roadmap row: `D4 Plugin admin | A Modules page … (AC-120 to AC-127). Done 2026-11-09`. `kernel.md`: `plugin_configuration` remains "added with the first configurable module", and the rule "disabling a plugin that an active quiz depends on" now includes scheduled runs and always-on plugins. Mark `plugin_configuration` in `data-model.md` as not created yet. `CLAUDE.md`: milestone list, Stav, "Další je D5". `flows.md`: new flow "Vypnutí modulu". Record with `make tech-debt-create title="D4: command to remove a module and reverse its migrations"`.

- [ ] **Step 4: Verify**

Run: `make tech-debt-check && uv run pytest tests/test_docs.py tests/test_tech_debt.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs CLAUDE.md app/api/CLAUDE.md app/domain/CLAUDE.md app/kernel/CLAUDE.md app/domain/settings.py .claude/skills/kvizotron-check-integration/flows.md tests
git commit -m "docs(plugins): D4 milestone documents, ADR-0057"
```

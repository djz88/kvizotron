# C4.5 UI Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shorter admin pages through a "Basic / All" switch and named setting groups, a run plan that shows only what differs, four quiz tabs plus "More", and a public "pages of questions" mode.

**Architecture:** Each setting definition gains `group` and `level`; one helper in `app/api` turns a form's fields into ordered groups with hidden counts, used by the global, quiz and plan pages. The switch is a cookie read by that helper. Pages mode is a fourth `Navigation` value handled by the existing client-side stepping in `flow.js`, which steps by a page of N questions instead of one.

**Tech Stack:** Django 6.1, Jinja2, HTMX, plain JS without build, pytest.

**Spec:** `docs/superpowers/specs/2026-11-08-c45-ui-simplification-design.md`

## Global Constraints

- Settings keep their keys, values and scopes (ADR-0042); the only new setting is `page_size`.
- Group keys, in this order: `playing`, `answers`, `participants`, `scoreboard`, `data`, `look`, `technical`. Levels: `basic`, `advanced`. Missing group → `technical`; missing level → `advanced`.
- Basic settings: `navigation_mode`, `page_size`, `attempt_limit`, `reveal_moment`, `repeat_attempts`, `ask_name`, `scoreboard_visibility`, `data_profile`, `color_palette`, `time_zone`.
- Switch cookie `kvz_admin_view`, values `basic` (default) and `all`. Works without JavaScript.
- `page_size`: choices `"2"`…`"20"`, default `"5"`, scopes `("global", "quiz")`, scope reason "Applies to the whole attempt, not to one question."
- Default `navigation_mode` becomes `step_back`; migration 0015 stores `all_at_once` globally when the database has an admin or a quiz and no stored global value.
- Admin texts cs and en; public texts cs, en, uk. Phone width, light and dark, keyboard. No inline script or style (CSP). No build step.
- Commands: `export PATH=<uv-0.13>/bin:$PATH`; `uv run pytest …`; `make quality`; `make messages` (revert `.mo` churn in untouched modules).

## Review Focus

1. A setting overridden on a quiz but advanced must show in "Basic" — otherwise an admin cannot see why a quiz behaves differently. Test in Task 4.
2. A refused value (form error) on a field hidden in "Basic" or in a collapsed plan group must be shown and its group opened. Tests in Tasks 4 and 5.
3. Pages mode with a question count not divisible by the size (12 / 5) and with a bank draw: last page shorter, progress "Questions 11–12 of 12". Test in Task 2 for the data attributes; browser in Task 8.
4. Pages mode + timer expiry + resume after reload returns to the same page with answers. Browser in Task 8 (JS has no automated tests, TD-039).
5. A module disabled (setting missing from the catalogue) must not break grouping or wipe values. Test in Task 3.

---

### Task 1: Group and level on every setting

**Files:**
- Modify: `app/contracts/__init__.py` (constants), `app/kernel/manifest.py:12` (`SettingDeclaration`), `app/domain/settings.py:147` (`SettingDefinition`), `:160` (`CATALOGUE` entries), `:358-376` (`register_modules`)
- Modify: manifests that declare settings: `app/plugins/participants/manifest.py`, `app/plugins/results/manifest.py`, `app/plugins/quiz_flow/manifest.py`, `app/plugins/questions/image_answer/manifest.py`, `app/providers/media_local/manifest.py` (and any other `settings` with entries — find with `grep -rl '"settings": \[$' app`)
- Test: `tests/domain/test_setting_groups.py`

**Interfaces:**
- Produces: `app.contracts.SETTING_GROUPS: tuple[str, ...]` (the seven keys in order), `BASIC = "basic"`, `ADVANCED = "advanced"`; `SettingDefinition.group: str = "technical"`, `SettingDefinition.level: str = "advanced"`; `SettingDeclaration.group`/`.level` same defaults, validated against `SETTING_GROUPS` and `(BASIC, ADVANCED)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_setting_has_a_known_group_and_level():
    for key, d in settings.CATALOGUE.items():
        assert d.group in SETTING_GROUPS, key
        assert d.level in (BASIC, ADVANCED), key

def test_basic_settings_are_exactly_the_first_cut():
    assert {k for k, d in settings.CATALOGUE.items() if d.level == BASIC} == {
        "navigation_mode", "page_size", "attempt_limit", "reveal_moment", "repeat_attempts",
        "ask_name", "scoreboard_visibility", "data_profile", "color_palette", "time_zone"}

@pytest.mark.parametrize("key,group", [("shuffle_options", "playing"), ("unfinished_attempt", "playing"),
    ("photo_visibility", "answers"), ("duplicate_names", "participants"), ("revision_mode", "scoreboard"),
    ("retention_period", "data"), ("announce_planned", "look"), ("grading_view", "technical")])
def test_group_of(key, group):
    assert settings.CATALOGUE[key].group == group

def test_manifest_refuses_an_unknown_group():
    with pytest.raises(ValidationError):
        SettingDeclaration(key="x", choices=["a"], default="a", label="X", value_labels={"a": "A"}, group="misc")
```

`page_size` does not exist until Task 2: keep it in the basic set; the test fails until Task 2 — mark `test_basic_settings_are_exactly_the_first_cut` with `xfail(strict=True, reason="page_size comes in Task 2")` and remove the mark in Task 2.

- [ ] **Step 2:** `uv run pytest tests/domain/test_setting_groups.py -q` → FAIL (`AttributeError: group`).
- [ ] **Step 3:** Add the constants, the two fields, pass them through `register_modules`, and set group/level on every domain entry and manifest entry per the spec table (spec "Admin: groups").
- [ ] **Step 4:** Same command → PASS (one xfail). `make wiring` → PASS.
- [ ] **Step 5: Commit** `feat(settings): group and level for every setting`

### Task 2: Pages of questions

**Files:**
- Modify: `app/domain/settings.py` (`Navigation.PAGES = "pages"`, `PAGE_SIZE = "page_size"` entry after `NAVIGATION_MODE`, `is_flow_conflict` :468, `Flow` :396 gains `page_size: int`, `flow` :499)
- Modify: `app/plugins/quiz_flow/plugin.py` (`modes()` adds `pages`; `client_options(mode, moment, page_size)` returns `{"step", "back", "check", "page": int}`), `tests/contracts/quiz_flow.py`
- Modify: `app/api/rendering.py:173` (`flow_options`), `app/api/jinja2/public/_questions.html` (`data-flow-page="N"`, progress texts), `app/api/assets/flow.js`, `app/api/assets/resume.js` (step index = page index)
- Modify: locale catalogues (domain, api, quiz_flow)
- Test: `tests/api/test_play_flow.py`, `tests/domain/test_flow_settings.py`, `tests/api/test_admin_layout.py`

**Interfaces:**
- Consumes: Task 1 fields (`PAGE_SIZE` is `group="playing"`, `level="basic"`).
- Produces: `settings.Navigation.PAGES`, `settings.PAGE_SIZE`, `Flow.page_size`.

- [ ] **Step 1: Failing tests**

```python
# tests/domain/test_flow_settings.py
def test_after_each_conflicts_with_pages():
    assert settings.is_flow_conflict("pages", "after_each")

def test_page_size_defaults_to_five_and_follows_the_quiz(quiz):
    assert settings.flow(quiz).page_size == 5
    settings.set_override("page_size", quiz, "12", admin_id=None)
    assert settings.flow(quiz).page_size == 12

# tests/api/test_play_flow.py
def test_pages_mode_carries_the_page_size(client, run):
    settings.set_override(settings.NAVIGATION_MODE, run.quiz, "pages", admin_id=None)
    settings.set_override(settings.PAGE_SIZE, run.quiz, "5", admin_id=None)
    html = start_page(client, run, "uk")
    assert 'data-flow="pages"' in html and 'data-flow-page="5"' in html
    assert 'data-flow-back' in html  # pages allow going back

# tests/api/test_admin_layout.py
def test_quiz_form_refuses_pages_with_inherited_after_each(logged_in):
    quiz = published_quiz()
    settings.set_global(settings.REVEAL_MOMENT, "after_each", admin_id=None)
    response = logged_in.post(f"{base(quiz)}/settings", behaviour(quiz, navigation_mode="pages"))
    assert response.status_code == 200 and settings.quiz_override("navigation_mode", quiz) is None
```

Also add the progress text `"Questions %(first)s–%(last)s of %(total)s"` to `test_progress_texts_are_translated` for cs and uk. Remove the xfail from Task 1.

- [ ] **Step 2:** `uv run pytest tests/domain/test_flow_settings.py tests/api/test_play_flow.py tests/api/test_admin_layout.py tests/domain/test_setting_groups.py -q` → the new tests FAIL.
- [ ] **Step 3:** Implement. `flow.js`: when `data-flow="pages"`, a "step" shows questions `[i*N, (i+1)*N)`; Next/Previous move by one page; progress uses the new text; `kvz:step` detail `index` is the page index so `resume.js` keeps working unchanged. Label of `pages`: cs "Po stránkách", en "Pages of questions", uk "Сторінками"; `page_size` label cs "Otázek na stránku", en "Questions per page", help "Only for pages of questions."
- [ ] **Step 4:** Same command → PASS. `make messages`, fill cs/uk, revert `.mo` churn elsewhere.
- [ ] **Step 5: Commit** `feat(flow): pages of questions`

### Task 3: Step mode as the default, existing installations unchanged

**Files:**
- Modify: `app/domain/settings.py` (`NAVIGATION_MODE` default → `Navigation.STEP_BACK`)
- Create: `app/domain/migrations/0015_navigation_default.py` (RunPython; reverse is a no-op)
- Test: `tests/domain/test_migration_0015.py` (pattern of `test_migration_0013.py`, including its fixture that migrates back to the leaf)

- [ ] **Step 1: Failing tests**

```python
def test_existing_installation_keeps_all_at_once(migrator):  # a quiz exists at 0014
    ...migrate to 0015...
    assert AppSetting.objects.get(key="navigation_mode", quiz=None).value_json == "all_at_once"

def test_stored_global_value_is_left_alone(migrator): ...  # stored "step_no_back" stays
def test_fresh_installation_gets_step_back(migrator): ...  # no admin, no quiz → no row; resolve() == "step_back"
```

- [ ] **Step 2:** `uv run pytest tests/domain/test_migration_0015.py -q` → FAIL.
- [ ] **Step 3:** Migration reads `kernel.AdminUser` and `domain.Quiz` via `apps.get_model`; depends on `0014_results` and the kernel's latest migration.
- [ ] **Step 4:** PASS; then the whole suite `uv run pytest -q` — fix tests that relied on the all-at-once default by setting it explicitly in the test (never weaken assertions).
- [ ] **Step 5: Commit** `feat(flow): one question at a time by default for new installations`

### Task 4: The switch and grouped settings pages

**Files:**
- Create: `app/api/admin_view.py` — `COOKIE = "kvz_admin_view"`; `is_basic(request) -> bool`; view `switch(request)` (POST `mode`, `next`; sets cookie for one year, `SameSite=Lax`, redirects to a same-site `next` via `url_has_allowed_host_and_scheme`, else `/admin/`); `group_fields(form, keys, *, differs: Callable[[str], bool], basic: bool) -> list[FieldGroup]`
- `FieldGroup`: `key: str`, `label: str`, `fields: list[BoundField]`, `hidden: int`, `open: bool` (has an error or a differing value)
- Modify: `app/api/admin_urls.py` (`path("view", admin_view.switch, name="admin_view")`), `app/api/jinja2/admin/base.html` (new `<li>` form with two buttons "Basic"/"All", current one `aria-pressed="true"`), `app/api/jinja2/admin/_setting_groups.html` (new: group links + headings with `id="group-<key>"` + fields + "%(count)s more in All"), `admin/settings.html`, `admin/quiz_settings.html`, `app/api/admin_settings.py`, `app/api/admin_quizzes.py:174` (`settings_page` passes groups)
- Modify: `app/plugins/theme_default/assets/theme.css` (rules for every new class; `make wiring` checks)
- Test: `tests/api/test_admin_view.py`

**Interfaces:**
- Consumes: Task 1 metadata, Task 2 `page_size`.
- Produces: `admin_view.is_basic`, `admin_view.group_fields`, `FieldGroup`, template `admin/_setting_groups.html` taking `groups`.

Rules: a field whose key is not in the catalogue (slug, featured, anonymous labels, minutes) stays where the form puts it; the anonymous labels belong to the `scoreboard` group and are advanced unless non-empty. `differs` on the global page: stored value ≠ catalogue default; on a quiz: `quiz_override(key, quiz) is not None` (labels: non-empty).

- [ ] **Step 1: Failing tests**

```python
def test_switch_sets_the_cookie_without_javascript(logged_in):
    r = logged_in.post("/admin/view", {"mode": "all", "next": "/admin/settings"})
    assert r.status_code == 302 and r["Location"] == "/admin/settings"
    assert r.cookies["kvz_admin_view"].value == "all"

def test_switch_refuses_a_foreign_next(logged_in):
    r = logged_in.post("/admin/view", {"mode": "all", "next": "https://evil.example/"})
    assert r["Location"] == "/admin/"

def test_global_page_lists_groups_in_order(logged_in):
    html = text(logged_in.get("/admin/settings?lang=en"))
    ids = re.findall(r'id="group-(\w+)"', html)
    assert ids == ["playing", "answers", "participants", "scoreboard", "data", "look", "technical"]

def test_basic_hides_advanced_and_counts_them(logged_in):
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert 'name="navigation_mode"' in html and 'name="shuffle_options"' not in html
    assert "more in All" in html

def test_all_shows_everything(logged_in):
    logged_in.cookies["kvz_admin_view"] = "all"
    assert 'name="shuffle_options"' in text(logged_in.get("/admin/settings"))

def test_overridden_advanced_setting_shows_in_basic(logged_in):  # Review Focus 1
    quiz = make_quiz()
    settings.set_override("shuffle_options", quiz, "on", admin_id=None)
    assert 'name="shuffle_options"' in text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))

def test_refused_hidden_field_is_shown_with_its_error(logged_in):  # Review Focus 2
    ...post a global form that refuses reveal_level-related conflict on an advanced field;
    assert the field and its error are in the 200 response...

def test_missing_module_settings_do_not_break_grouping(): ...  # Review Focus 5:
    # group_fields over keys that include one absent from the catalogue → it is skipped, others grouped

def test_saving_in_basic_keeps_hidden_values(logged_in):
    # a stored advanced global value survives a POST of the basic form (absent field ≠ empty value)
```

- [ ] **Step 2:** `uv run pytest tests/api/test_admin_view.py -q` → FAIL.
- [ ] **Step 3:** Implement. Hidden fields are not rendered; the save paths in `admin_settings.py` and `quiz_settings` (`admin_quizzes.py:240-258`) change only keys present in `request.POST`, so a hidden setting is never reset. Group labels (cs/en): Playing/Průchod, Answers and result/Odpovědi a výsledek, Participants/Účastníci, Scoreboard/Žebříček, Data/Data, Look and listing/Vzhled a výpis, Technical/Technické.
- [ ] **Step 4:** PASS; `uv run pytest tests/api -q` → PASS (update layout tests that count fields only by scoping, never by weakening).
- [ ] **Step 5: Commit** `feat(admin): basic and all views with setting groups`

### Task 5: Run plan shows what differs

**Files:**
- Modify: `app/api/admin_forms.py:314` (`RunPlanForm` keeps its fields), `app/api/admin_runs.py:124` (`_plan_page` builds groups with `group_fields`, `differs` = chosen value ≠ the quiz's value from `run_plan`'s initial), `app/api/jinja2/admin/run_plan.html`
- Test: `tests/api/test_run_plan.py`

Layout: start, deadline, limit visible; sentence "The run takes the quiz's settings." with a link to the quiz Settings tab; each group a `<details>` with `open` when `FieldGroup.open`; `data_profile`, `retention_period` in `data`; `access_code`, `generate_code` in `participants`. The switch applies inside groups as in Task 4.

- [ ] **Step 1: Failing tests**

```python
def test_plan_groups_are_closed_when_nothing_differs(logged_in):
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/plan"))
    assert "<details" in html and "<details open" not in html

def test_group_with_a_quiz_override_is_not_relevant_but_a_run_change_opens(logged_in):
    # re-render after a refused POST with scoreboard_visibility="live" + data_profile="none":
    # the data and scoreboard groups render <details open> and the error text is present

def test_time_fields_stay_visible(logged_in):
    # name="starts_at" appears before the first "<details"
```

- [ ] **Step 2:** `uv run pytest tests/api/test_run_plan.py -q` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** PASS; `uv run pytest tests/api -q` → PASS.
- [ ] **Step 5: Commit** `feat(admin): run plan shows only what differs`

### Task 6: Run page in basic view, quiz tabs with More

**Files:**
- Modify: `app/api/jinja2/admin/run.html` (wrap :16 access code — shown when a code is set or `not basic`; :33 data section, merge/unmerge forms inside :47-82, deadline/period forms :163 → only when `not basic`), `app/api/admin_runs.py` (pass `basic`)
- Modify: `app/api/jinja2/admin/_quiz_header.html:2,30` (tabs: Questions, Runs, Grading, Settings; `<details class="more">` "More" with Test links and Revisions; summary gets `aria-current="page"` when the tab is one of them)
- Modify: `theme.css` if a new class is needed
- Test: `tests/api/test_admin_layout.py`, `tests/api/test_admin_scoreboard.py`

- [ ] **Step 1: Failing tests**

```python
def test_tabs_are_four_and_more(logged_in):
    html = text(logged_in.get(f"{base(quiz)}/edit"))
    nav = html[html.index('class="tabs"'):]
    assert re.findall(r'<li><a href="[^"]+/(edit|runs|grading|settings)"', nav) == ["edit", "runs", "grading", "settings"]
    assert f"{base(quiz)}/tests" in nav and f"{base(quiz)}/revisions" in nav

def test_more_is_current_on_revisions(logged_in): ...  # summary carries aria-current on /revisions

def test_run_page_basic_hides_deeper_sections(logged_in):
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert 'id="statistics"' in html and 'id="scoreboard"' in html
    assert "/merge" not in html and "/period" not in html

def test_run_page_basic_shows_a_set_code(logged_in): ...
def test_run_page_all_shows_everything(logged_in): ...  # cookie all → /merge, /period present
```

Update `current_tab` helper only if it can no longer read the current tab; keep its assertions.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** `uv run pytest tests/api -q` → PASS.
- [ ] **Step 5: Commit** `feat(admin): four tabs with More, shorter run page`

### Task 7: Public background on long pages

**Files:** `app/plugins/theme_default/assets/theme.css:550`

- [ ] **Step 1:** In `kvizotron-browser` (rebuilt per `kvizotron-browser-walkthrough`), open a quiz with 12+ questions all at once at 1280×900, scroll to the bottom, take a viewport (not full-page) screenshot. Also check 390 px.
- [ ] **Step 2:** If the gradient covers the viewport while scrolled, the earlier finding was a full-page screenshot artefact of `background-attachment: fixed`: record "no defect" in the ledger and skip to Task 8. Otherwise paint the gradient on `html` (`min-height: 100%`) instead of `body`, and re-check both widths.
- [ ] **Step 3: Commit** (only if changed) `fix(theme): public background on long pages`

### Task 9: Logo on the public portal (user request 2026-11-08, added after approval)

**Files:**
- Create: `app/api/assets/logo.svg` (copy of the user's `Kvizotron-logo.svg` from the repository root, unchanged; it has no script or external reference)
- Modify: `app/api/public.py:55-68` (asset map: `"logo.svg": "image/svg+xml"`), `app/plugins/theme_default/jinja2/theme_default/layout.html:9,21` (`<link rel="icon" type="image/svg+xml" href="/assets/logo.svg">` before the PNG icon; `<img class="site-logo" src="/assets/logo.svg" alt="" width="32" height="32">` inside `.site-name`, so admin and public bars both show it), `app/api/jinja2/public/about.html` (logo 160 px above the heading, `alt="Kvízotron"`), `app/api/jinja2/public/index.html` hero if it has one (logo 96 px), `theme.css` (`.site-logo`, `.about-logo`: rounded corners, the black square is part of the mark)
- Test: `tests/api/test_public_layout.py`

- [ ] **Step 1: Failing tests**

```python
def test_logo_is_served(client):
    r = client.get("/assets/logo.svg")
    assert r.status_code == 200 and r["Content-Type"].startswith("image/svg+xml")

def test_bar_and_about_show_the_logo(client):
    assert 'class="site-logo"' in text(client.get("/"))
    assert 'src="/assets/logo.svg"' in text(client.get("/about"))
```

- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** `uv run pytest tests/api/test_public_layout.py -q` → PASS; `make wiring` → PASS.
- [ ] **Step 5: Commit** `feat(theme): Kvízotron logo in the bar and on About`

The browser walkthrough in Task 8 also covers the logo on the home page, About and the admin bar, light and dark, 390 px.

### Task 8: Docs, ADR, verification

**Files:**
- Create: `docs/_architecture/adr/0052-setting-groups-levels-and-step-default.md` (MADR 4: groups and levels as setting metadata, the switch cookie, pages mode, new default with migration)
- Modify: `docs/_architecture/adr/README.md`, `acceptance-criteria.md` (AC-86 groups and switch, AC-87 plan shows differences, AC-88 pages mode, AC-89 default and migration; tests from Tasks 2–6 name them in docstrings), `roadmap.md` (row `C4.5 UI simplification` before C5, `Done 2026-11-08` at the end), `modules/api-ui.md` (tabs, switch, groups, plan), `modules/domain.md` (Navigation, page size), `docs/plugin-api.md` (`group`, `level` in `SettingDeclaration`), `CLAUDE.md` (milestone list, Stav, "Další je C5"), `app/api/CLAUDE.md`, `app/domain/CLAUDE.md`, `.claude/skills/kvizotron-add-setting/SKILL.md` (choose group and level), `.claude/skills/kvizotron-check-integration/flows.md` (pages mode)

- [ ] **Step 1:** Write the docs; `uv run pytest tests/test_docs.py -q` → PASS.
- [ ] **Step 2:** `make quality` → all pass. `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke` → OK.
- [ ] **Step 3:** Browser walkthrough (`kvizotron-browser-walkthrough`) on a new quiz `c45-…`: global and quiz settings in Basic and All; plan form with a changed group; run page; tabs and More on a phone; a participant through pages (12 questions, size 5) on 390 px dark uk, going back, reload restores page and answers, timer expiry submits.
- [ ] **Step 4: Commit** `docs: C4.5 UI simplification`

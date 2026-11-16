# Hero Logo Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin can hide the large logo on `/` and `/about`; a quiz page shows the large logo when the quiz has its own; uploaded logos no longer sit on a white plate; a set logo is removed with a visible button.

**Architecture:** One new catalogue setting `show_hero_logo` (global only, `on`/`off`, default `on`, group `look`, level BASIC) governs `/` and `/about`. The quiz page shows the quiz's own hero logo iff `Branding.sources["hero_logo"] == "quiz"` (no setting: uploading it is the switch, so it is hidden by default). The plate stays only around the built-in hero logo. `branding.resolve` exposes both facts as `Branding.show_hero_logo` and `Branding.quiz_hero_logo`.

**Tech Stack:** Django, Jinja2, pytest, `theme.css`.

## Global Constraints

- UI: **běh**/run, never "kolo". Admin texts exist in cs and en, public ones also in uk (`tests/test_translations.py`); run `make messages` and fill `msgstr` in cs and uk; revert unrelated `.mo` noise (keep only `app/api` and changed `.po`).
- ADR-0042: a narrower scope needs `scope_reason`. `show_hero_logo` is `("global",)` with the reason "The large logo is shown on pages that belong to no quiz."
- Setting values are read only via `settings.resolve(key, quiz)`; `AppSetting` is never read directly.
- Uploaded or fetched logos are never replaced or hidden by the built-in-logo logic.
- No inline script/style (CSP). Every behaviour change has a test that failed first.
- Classification VELKÁ (UI + domain, ADR-0054 addendum). Run `kvizotron-check-applied` before the final review; browser walkthrough (`kvizotron-browser-walkthrough`, keep stack data) before finishing.

## Decisions (user, 2026-11-11)

1. `show_hero_logo`: global only, one switch for `/` and `/about`, default shown.
2. Quiz page: shows the quiz's own large logo; default not shown. No second setting.
3. The plate is only for the built-in hero logo; uploaded/fetched hero logos have none (regression fix).
4. A set logo is removed by a button ("Remove the logo", "Remove the landing page logo") instead of a checkbox.
5. Not in scope: a quiz-level choice to show an inherited or built-in large logo on a quiz page.

## File Structure

- Modify `app/domain/settings.py` — constant `SHOW_HERO_LOGO`, `CATALOGUE` entry.
- Modify `app/domain/branding.py` — `Branding.show_hero_logo`, `Branding.quiz_hero_logo`, `resolve()`.
- Modify `app/api/jinja2/public/_hero_logo.html` — plate only for the built-in logo.
- Modify `app/api/jinja2/public/landing.html`, `about.html` — `{% if branding.show_hero_logo %}`.
- Modify `app/api/jinja2/public/quiz.html` — hero logo when `branding.quiz_hero_logo`.
- Modify `app/api/jinja2/admin/_branding_fields.html`, `app/api/admin_view.py` — removal buttons.
- Modify `docs/_architecture/modules/api-ui.md` (table "Where things are set"), `acceptance-criteria.md` (AC-149, AC-150), `adr/0054-…md` (addendum), `README.md` (AC range).
- Tests: `tests/domain/test_branding.py`, `tests/domain/test_settings.py` (find with `grep -ln CATALOGUE tests/domain`), `tests/api/test_branding_pages.py`, `tests/api/test_admin_branding.py`.

## Interfaces

```python
# app/domain/settings.py
SHOW_HERO_LOGO = "show_hero_logo"
# CATALOGUE[SHOW_HERO_LOGO]: choices ("off","on"), default "on", scopes ("global",), group "look", level BASIC

# app/domain/branding.py  (Branding gains two fields; existing ones unchanged)
show_hero_logo: bool   # settings.resolve(SHOW_HERO_LOGO) == "on"; for / and /about
quiz_hero_logo: bool   # quiz is not None and sources["hero_logo"] == "quiz"; for the quiz page
```

---

### Task 1: The setting and the two facts

**Files:** Modify `app/domain/settings.py`, `app/domain/branding.py`; Test `tests/domain/test_branding.py`, the settings test module.

**Interfaces:** Produces `settings.SHOW_HERO_LOGO`, `Branding.show_hero_logo`, `Branding.quiz_hero_logo`.

- [ ] **Step 1: Write failing tests** (append to `tests/domain/test_branding.py`; `png`, `make_quiz`, `ADMIN_ID`, `settings` already imported there):

```python
def test_the_large_logo_is_shown_by_default():
    assert branding.resolve(None, "cs").show_hero_logo is True


def test_the_large_logo_can_be_hidden_globally():
    settings.set_global(settings.SHOW_HERO_LOGO, "off", admin_id=ADMIN_ID)
    assert branding.resolve(None, "cs").show_hero_logo is False


def test_the_switch_is_global_only():
    assert settings.CATALOGUE[settings.SHOW_HERO_LOGO].scopes == ("global",)
    assert settings.CATALOGUE[settings.SHOW_HERO_LOGO].scope_reason


def test_a_quiz_shows_its_large_logo_only_when_it_has_its_own():
    quiz = make_quiz()
    assert branding.resolve(quiz, "cs").quiz_hero_logo is False
    branding.set_hero_logo(None, png(), admin_id=ADMIN_ID)  # a global one is not the quiz's
    assert branding.resolve(quiz, "cs").quiz_hero_logo is False
    branding.set_hero_logo(quiz, png("blue"), admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "cs").quiz_hero_logo is True


def test_there_is_no_quiz_large_logo_without_a_quiz():
    assert branding.resolve(None, "cs").quiz_hero_logo is False
```

- [ ] **Step 2:** `uv run pytest tests/domain/test_branding.py -q -k "large_logo or switch_is_global"` → FAIL (`AttributeError`).
- [ ] **Step 3: Implement.** In `settings.py` add `SHOW_HERO_LOGO = "show_hero_logo"` beside the other constants and this entry in `CATALOGUE` (after `SHOW_SOURCES`):

```python
    SHOW_HERO_LOGO: SettingDefinition(
        SHOW_HERO_LOGO,
        tuple(Switch),
        Switch.ON.value,
        gettext_lazy("Large logo on the home and About pages"),
        {Switch.ON: gettext_lazy("Show"), Switch.OFF: gettext_lazy("Hide")},
        ("global",),
        "The large logo is shown on pages that belong to no quiz.",
        group="look",
        level=BASIC,
    ),
```

(`Switch` is declared before `CATALOGUE`; keep positional order `key, choices, default, label, value_labels, scopes, scope_reason`.) In `branding.py` add to `Branding` (after `logo_family`):

```python
    show_hero_logo: bool  # the home and About pages
    quiz_hero_logo: bool  # a quiz page, only for the quiz's own large logo
```

and in `resolve()` before `return Branding(`:

```python
    show_hero_logo = settings.resolve(settings.SHOW_HERO_LOGO) == settings.Switch.ON
    quiz_hero_logo = quiz is not None and sources["hero_logo"] == "quiz"
```

passing `show_hero_logo=show_hero_logo, quiz_hero_logo=quiz_hero_logo`. If `settings` in `branding.py` is the `app.domain.settings` module (it is: `from app.domain import ... settings`), no new import is needed.

- [ ] **Step 4:** run the new tests, then `uv run pytest tests/domain tests/contracts -q` → PASS (`test_settings_rule` validates the entry).
- [ ] **Step 5: Commit** `feat(branding): switch for the large logo and the quiz's own large logo` (Co-Authored-By line from the session attribution).

---

### Task 2: Pages

**Files:** Modify `_hero_logo.html`, `landing.html`, `about.html`, `quiz.html`; Test `tests/api/test_branding_pages.py`.

**Interfaces:** Consumes `branding.show_hero_logo`, `branding.quiz_hero_logo`, `branding.hero_logo_dark_url` (None for a chosen logo).

- [ ] **Step 1: Write failing tests.** Existing test `test_overriding_only_the_hero_logo_keeps_the_plate_and_the_bar_logo` asserts the plate for an uploaded logo: **rewrite** it (Decision 3) to the first test below; keep its bar-logo assertion. Add the rest. Helpers `text`, `FormClient`, `png_bytes`, `brand`, `BAR`, `ADMIN_ID`, `settings`, `branding` exist in the module; a quiz with a public page: `published_quiz()` (see how other tests in the file reach `/q/<slug>`; reuse the same call).

```python
def test_an_uploaded_large_logo_has_no_plate_and_no_dark_source():
    branding.set_hero_logo(None, png_bytes(), admin_id=ADMIN_ID)
    html = text(FormClient().get("/"))
    assert re.search(BAR, html)
    assert 'class="about-logo' in html and "/media/" in html
    assert "hero-logo-plate" not in html and "<source" not in html


def test_the_built_in_large_logo_keeps_its_plate(client):
    assert 'class="hero-logo-plate"' in text(client.get("/"))


@pytest.mark.parametrize("path", ["/", "/about"])
def test_hiding_the_large_logo_hides_it_on_both_pages(path):
    settings.set_global(settings.SHOW_HERO_LOGO, "off", admin_id=ADMIN_ID)
    html = text(FormClient().get(path))
    assert 'class="about-logo' not in html and "hero-logo-plate" not in html
    assert re.search(BAR, html)  # the bar logo stays


def test_a_quiz_page_shows_no_large_logo_by_default():
    quiz = published_quiz()
    assert 'class="about-logo' not in text(FormClient().get(f"/q/{quiz.slug}"))


def test_a_quiz_page_shows_the_quizs_own_large_logo():
    quiz = published_quiz()
    branding.set_hero_logo(quiz, png_bytes(), admin_id=ADMIN_ID)
    html = text(FormClient().get(f"/q/{quiz.slug}"))
    assert 'class="about-logo' in html and "/media/" in html


def test_a_global_large_logo_does_not_appear_on_a_quiz_page():
    quiz = published_quiz()
    branding.set_hero_logo(None, png_bytes(), admin_id=ADMIN_ID)
    assert 'class="about-logo' not in text(FormClient().get(f"/q/{quiz.slug}"))
```

If `published_quiz()` yields a quiz whose `/q/<slug>` needs an open run, use the helper the neighbouring tests use (`open_quiz_run` in `tests.domain.helpers`, then `run.quiz.slug`).

- [ ] **Step 2:** `uv run pytest tests/api/test_branding_pages.py -q` → the new/rewritten tests FAIL.
- [ ] **Step 3: Implement.** `_hero_logo.html`:

```jinja
{# `width`, `height` and `alt` come from the includer. The built-in logo sits on a plate so that it reads on any page colour; a chosen logo is shown as it is. #}
{% set builtin = branding.hero_logo_dark_url %}
{% if builtin %}<div class="hero-logo-plate">{% endif %}
  <picture>
    {% if builtin %}<source media="(prefers-color-scheme: dark)" srcset="{{ branding.hero_logo_dark_url }}">{% endif %}
    <img class="about-logo about-logo-centered" src="{{ branding.hero_logo_url }}" alt="{{ alt }}" width="{{ width }}" height="{{ height }}">
  </picture>
{% if builtin %}</div>{% endif %}
```

`landing.html` line 4 and `about.html` line 4: wrap the `{% with … %}{% include "public/_hero_logo.html" %}{% endwith %}` in `{% if branding.show_hero_logo %}…{% endif %}`. `quiz.html`: inside `<div class="hero">`, before `<h1>`:

```jinja
    {% if branding.quiz_hero_logo %}{% with width=144, height=100, alt=branding.name %}{% include "public/_hero_logo.html" %}{% endwith %}{% endif %}
```

- [ ] **Step 4:** run `tests/api/test_branding_pages.py tests/api/test_public_layout.py` → PASS; then `uv run pytest tests/api -q` (≈2 min, run in background and read the tail).
- [ ] **Step 5: Commit** `feat(branding): large logo switch on the pages, quiz large logo, no plate for chosen logos`.

---

### Task 3: Admin — switch visible, removal buttons

**Files:** Modify `app/api/jinja2/admin/_branding_fields.html`; Test `tests/api/test_admin_branding.py`.

**Interfaces:** Consumes `logo_preview` (the resolved `Branding` of the level, set in both settings views) and `branding_sources`; the existing `clear` POST (`admin_branding.py`: `clear=logo` / `clear=hero_logo` already call `remove_logo` / `remove_hero_logo` for `quiz` or `None`).

- [ ] **Step 1: Write failing tests** (module has `showing_all`, `uploading`, `png`, `quiz_url`, `text`, `branding`, `GLOBAL`):

```python
def test_the_global_settings_offer_the_large_logo_switch(showing_all):
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'name="show_hero_logo"' in html


def test_a_quiz_does_not_offer_the_large_logo_switch(showing_all):
    html = text(showing_all.get(quiz_url(make_quiz(), "settings") + "?lang=en"))
    assert 'name="show_hero_logo"' not in html


def test_saving_the_switch_hides_the_large_logo(showing_all, client):
    showing_all.post("/admin/settings", {"show_hero_logo": "off"})
    assert branding.resolve(None, "cs").show_hero_logo is False
```

(use the global settings URL the file's other tests post to; `GLOBAL` is the branding one: grep `/admin/settings"` in `tests/api/test_admin_settings*.py` for the settings form URL.)

```python
def test_a_set_logo_is_removed_by_a_button(showing_all):
    branding.set_logo(None, png().read(), admin_id=ADMIN_ID)
    branding.set_hero_logo(None, png().read(), admin_id=ADMIN_ID)
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'name="clear" value="logo"' in html and 'name="clear" value="hero_logo"' in html
    assert 'type="checkbox" name="remove_logo"' not in html
    showing_all.post(GLOBAL, {"clear": "logo"})
    assert branding.resolve(None, "cs").sources["logo"] == "default"


def test_no_removal_button_without_a_set_logo(showing_all):
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'name="clear" value="logo"' not in html and 'name="clear" value="hero_logo"' not in html
```

- [ ] **Step 2:** run them → FAIL (switch test may already pass because `GlobalSettingsForm` picks up catalogue keys — then keep it as a guard; the button tests must FAIL).
- [ ] **Step 3: Implement.** In `_branding_fields.html` skip the two checkbox fields in the loop (`{% if field.name not in ("remove_logo", "remove_hero_logo") %}` around `{{ field.as_field_group() }}` and the existing inherited/“Remove override” block for them) and render buttons in the separate-forms area. Replace the final block with:

```jinja
  {# Separate forms, so that Enter in a text field submits Save and never a removal. #}
  {% set own = {} %}
  {% if branding_sources %}
    {% for base in ("name", "motto", "footer", "contact_email", "logo", "hero_logo") if branding_sources[base] == "quiz" %}{% set _ = own.update({base: true}) %}{% endfor %}
  {% else %}
    {% for base in ("logo", "hero_logo") if logo_preview.sources[base] != "default" %}{% set _ = own.update({base: true}) %}{% endfor %}
  {% endif %}
  {% for base in own %}
  <form method="post" id="clear-{{ base }}" action="{{ branding_action }}">
    {{ csrf_input }}
    <input type="hidden" name="clear" value="{{ base }}">
    {% if base == "logo" %}<button type="submit" class="secondary outline">{{ _("Remove the logo") }}</button>
    {% elif base == "hero_logo" %}<button type="submit" class="secondary outline">{{ _("Remove the landing page logo") }}</button>{% endif %}
  </form>
  {% endfor %}
```

Existing quiz-level “Remove override” buttons are rendered next to their fields with `form="clear-{{ base }}"` (they keep working); for `logo` / `hero_logo` render the same `form="clear-…"` button right after the `logo_source` / `hero_logo_source` field group instead of the checkbox, labelled `_("Remove the logo")` / `_("Remove the landing page logo")`, only when `own[base]` — then the buttons in the separate-forms block above carry no visible label duplicate: keep **one** button per logo, the one beside its field, and leave the separate form empty except the hidden input. Read the template once before editing and keep that single-button rule. `branding_action` at the global level must be the branding POST URL (it already is for the global page: the tests' `GLOBAL`).

- [ ] **Step 4:** `uv run pytest tests/api/test_admin_branding.py tests/api/test_branding_pages.py -q` → PASS; update any existing test that posts `remove_logo`/`remove_hero_logo` through the form only if it renders the checkbox (the form fields still exist, so posting them keeps working).
- [ ] **Step 5:** `make messages`; add cs/uk `msgstr` for the new texts ("Large logo on the home and About pages", "Show", "Hide" if not yet present); revert `.mo` noise outside `app/api`; commit `feat(branding): removal buttons for logos`.

---

### Task 4: Docs, quality, browser

- [ ] **Step 1:** `docs/_architecture/modules/api-ui.md`: in "Where things are set → Nastavení" add "the switch for the large logo (global only)". ADR-0054 addendum 2026-11-11: switch `show_hero_logo` (global, reason: pages without a quiz), quiz page shows the quiz's own large logo only, plate only around the built-in one, removal by button. `acceptance-criteria.md`: `AC-149` (switch hides the large logo on `/` and `/about`, bar logo stays; global only) and `AC-150` (a quiz page shows its own large logo only, never an inherited one; a chosen logo has no plate; a set logo is removed by a button). Name them in test docstrings (`"""AC-149."""` in the page and domain tests, `"""AC-150."""` in the quiz-page and button tests). Bump the range in `docs/_architecture/README.md` to `AC-150`.
- [ ] **Step 2:** `uv run pytest tests/test_docs.py tests/test_wiring.py -q` → PASS (`test_wiring` needs `show_hero_logo` read by code: `branding.resolve` does).
- [ ] **Step 3:** `make quality` (≈4 min, background, read the tail) → green.
- [ ] **Step 4: Browser** (`kvizotron-browser-walkthrough`, rebuild stack from the worktree as that skill says; admin login state may be expired: ask for the password or the saved state): (a) switch off → `/` and `/about` without the large logo, bar logo stays; (b) a throwaway quiz `h-…` with its own large logo → quiz page shows it without a plate; (c) uploaded global large logo with white text shows with no plate; (d) buttons remove a set logo; light and dark, 390 px.
- [ ] **Step 5: Commit** `docs(branding): ADR-0054 addendum, AC-149 and AC-150`.

## Self-Review

- Decisions 1–5 map to Tasks 1–3; docs/quality/browser to Task 4.
- Names used identically: `SHOW_HERO_LOGO`, `Branding.show_hero_logo`, `Branding.quiz_hero_logo`, `clear` values `logo` / `hero_logo`.
- Known soft spot: Task 3 template step relies on reading `_branding_fields.html` first; the rule (one removal button per logo, beside its field, shown only when the level owns the logo) is the binding part.

# Default Logo Families Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The built-in logo follows the active palette (three families: Aurora, Mint, Amber) and is always readable, whatever the background colour or light/dark mode.

**Architecture:** The domain (`app/domain/branding.py`) picks a *logo family* from the resolved palette (preset table; hue of `custom.main` for `custom`) and exposes three built-in URLs on `Branding`: bar (dark square mark), hero light and hero dark. An uploaded or fetched logo is never replaced. Readability is guaranteed by layout, not by choosing a variant for the page colour: the bar is always dark, the hero logo sits on a neutral plate (`--kvz-card`) and a `<picture>` picks the light or dark drawing by `prefers-color-scheme`.

**Tech Stack:** Django, Jinja2, pytest, plain CSS (`theme.css`), SVG from `kvizotron_v4/`.

## Global Constraints

- Docs in `docs/` are English; UI texts are translated (cs/en/uk) via `make messages`; `.po` and `.mo` are in git.
- App is **Kvízotron**; in UI `QuizRun` is "běh"/"run", never "kolo".
- Domain owns logo resolution; theme owns palettes and derivation (ADR-0054). The theme must not import the domain.
- An uploaded/fetched logo (source `quiz` or `global`) is never replaced or wrapped by the new logic. Only `source == "default"` uses the families.
- Built-in SVGs: pure vector, no `<script>`, no `href=`, no `<image>`, no `data:` (the v4 files already comply).
- Every behaviour change has a test; no test is deleted or weakened except those that assert the replaced files (`logo.png`, `logo-full.svg`), which are rewritten to assert the new ones with equal strictness.
- Browser check required (UI change): skill `kvizotron-browser-walkthrough`, keep the `kvizotron-browser` stack data.
- Classification VELKÁ (UI + domain, ADR change). Run `kvizotron-check-applied` before `review-roles`.

## Decisions (accepted by the user on 2026-11-11)

1. Hero logo always on a card-coloured plate.
2. Custom colour → family by hue of `custom.main`: Amber 330–360° and 0–70°, Mint 70–200°, Aurora 200–330°.
3. Admin settings page shows which built-in logo applies.
4. Bar: dark 34 px square mark. Hero: "full" logo (02), not the wordmark (03).
5. Favicon and apple-touch icon stay as they are (out of scope).

Preset table: `indigo_pink`, `violet_white` → aurora; `blue_teal`, `green_blue` → mint; `red_plum` → amber.

## File Structure

- Create `app/api/assets/logo-{aurora,mint,amber}-bar.svg` ← `kvizotron_v4/0{1,2,3}-*/01-ctverec-KT-34px-dark.svg`
- Create `app/api/assets/logo-{aurora,mint,amber}-hero-light.svg` ← `…/02-full-ikony-pod-logem-light.svg`
- Create `app/api/assets/logo-{aurora,mint,amber}-hero-dark.svg` ← `…/02-full-ikony-pod-logem-dark.svg`
  (01 = Aurora-Neon, 02 = Cyber-Mint → `mint`, 03 = Solar-Amber → `amber`)
- Delete `app/api/assets/logo.png`, `logo-full.svg`, `logo.svg` (the uncommitted working-tree versions are replaced; `git rm` the tracked ones, delete the untracked one).
- Modify `app/api/public.py:52` — `SERVED_ASSETS`.
- Modify `app/domain/branding.py` — constants, `logo_family()`, `Branding` fields, `resolve()`.
- Create `app/api/jinja2/public/_hero_logo.html` — shared hero logo partial.
- Modify `app/api/jinja2/public/landing.html:4`, `about.html:4`, `app/plugins/theme_default/jinja2/theme_default/layout.html:39`.
- Modify `app/plugins/theme_default/assets/theme.css` (~line 374) — plate.
- Modify `app/api/jinja2/admin/_branding_fields.html` + the two view functions that render it — preview.
- Modify `docs/_architecture/adr/0054-branding-owned-by-domain-and-theme.md` (addendum, built-in logo line 34), `docs/_architecture/acceptance-criteria.md` (new AC), `TECH_DEBT.md` only if something is deferred.
- Tests: `tests/domain/test_branding.py`, `tests/api/test_public_layout.py`, `tests/api/test_branding_pages.py`, `tests/api/test_admin_branding.py`.

## Interfaces

```python
# app/domain/branding.py
LOGO_FAMILIES = ("aurora", "mint", "amber")
PRESET_FAMILY: dict[str, str]            # preset key -> family
def logo_family(palette: str, custom: DerivedPalette | None) -> str: ...

@dataclass(frozen=True)
class Branding:
    ...                                   # existing fields unchanged
    logo_url: str                         # bar; built-in => "/assets/logo-<family>-bar.svg"
    hero_logo_url: str                    # hero light; built-in => "/assets/logo-<family>-hero-light.svg"
    hero_logo_dark_url: str | None        # only for a built-in hero logo, else None
    logo_family: str                      # always set; used by the admin preview
```

---

### Task 1: Assets and serving

**Files:**
- Create: the nine SVGs above
- Delete: `logo.png`, `logo-full.svg`, `logo.svg` in `app/api/assets/`
- Modify: `app/api/public.py:52-72`
- Test: `tests/api/test_public_layout.py:156-205` (rewrite)

**Interfaces:**
- Produces: URLs `/assets/logo-<family>-{bar,hero-light,hero-dark}.svg` served as `image/svg+xml` for family in `aurora|mint|amber`.

- [ ] **Step 1: Write failing tests** — replace `test_logo_is_served`, `test_logo_is_the_designers_drawing`, `test_logo_full_*` with:

```python
FAMILIES = ("aurora", "mint", "amber")
KINDS = ("bar", "hero-light", "hero-dark")
NAMES = [f"logo-{f}-{k}.svg" for f in FAMILIES for k in KINDS]


def served(client, name):
    return b"".join(client.get(f"/assets/{name}").streaming_content).decode()


@pytest.mark.parametrize("name", NAMES)
def test_builtin_logo_is_served_as_svg(client, name):
    response = client.get(f"/assets/{name}")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("image/svg+xml")


@pytest.mark.parametrize("name", NAMES)
def test_builtin_logo_is_plain_vector(client, name):
    svg = served(client, name)
    for forbidden in ("<script", "href=", "<image", "data:", "onload"):
        assert forbidden not in svg


@pytest.mark.parametrize("family", FAMILIES)
def test_builtin_logo_shapes(client, family):
    assert 'viewBox="0 0 240.00 240.00"' in served(client, f"logo-{family}-bar.svg")
    for kind in ("hero-light", "hero-dark"):
        assert 'viewBox="0 0 1100 760"' in served(client, f"logo-{family}-{kind}.svg")


@pytest.mark.parametrize("old", ["logo.png", "logo-full.svg", "logo.svg"])
def test_replaced_logo_names_are_gone(client, old):
    assert client.get(f"/assets/{old}").status_code == 404
```

- [ ] **Step 2:** `uv run pytest tests/api/test_public_layout.py -k "builtin or replaced" -v` → FAIL (404).
- [ ] **Step 3: Copy files and register**

```bash
cd <repo>
copy() { cp "kvizotron_v4/$1/$2" "app/api/assets/logo-$3-$4.svg"; }
for pair in "01-Aurora-Neon aurora" "02-Cyber-Mint mint" "03-Solar-Amber amber"; do
  set -- $pair
  copy "$1" 01-ctverec-KT-34px-dark.svg "$2" bar
  copy "$1" 02-full-ikony-pod-logem-light.svg "$2" hero-light
  copy "$1" 02-full-ikony-pod-logem-dark.svg "$2" hero-dark
done
git rm -q app/api/assets/logo.png; git rm -q --cached app/api/assets/logo-full.svg; rm app/api/assets/logo-full.svg app/api/assets/logo.svg
```

In `SERVED_ASSETS` remove `"logo.png"` and `"logo-full.svg"`; add:

```python
    **{
        f"logo-{family}-{kind}.svg": "image/svg+xml"
        for family in ("aurora", "mint", "amber")
        for kind in ("bar", "hero-light", "hero-dark")
    },
```

- [ ] **Step 4:** run the same tests → PASS. (Tests that still mention `/assets/logo.png` fail until Tasks 2–3; that is expected here.)
- [ ] **Step 5: Commit** `git add app/api/assets app/api/public.py tests/api/test_public_layout.py && git commit -m "feat(branding): built-in logo files for three families"` (with the Co-Authored-By line from the session attribution).

---

### Task 2: Family choice in the domain

**Files:**
- Modify: `app/domain/branding.py:39-42, 55-66, 177-190, 204-206`
- Test: `tests/domain/test_branding.py`

**Interfaces:**
- Consumes: `theme().derive_palette(colours).main` (hex string), `settings.CATALOGUE[COLOR_PALETTE].default`.
- Produces: `logo_family`, `Branding.logo_url`, `.hero_logo_url`, `.hero_logo_dark_url`, `.logo_family` (see Interfaces above).

- [ ] **Step 1: Write failing tests**

```python
import pytest
from app.contracts import BrandColours
from app.domain import branding


@pytest.mark.parametrize(
    "preset,family",
    [("indigo_pink", "aurora"), ("violet_white", "aurora"), ("blue_teal", "mint"),
     ("green_blue", "mint"), ("red_plum", "amber")],
)
def test_preset_picks_its_logo_family(preset, family):
    assert branding.logo_family(preset, None) == family


@pytest.mark.parametrize(
    "main,family",
    [("#ff0000", "amber"), ("#ffa500", "amber"), ("#ff0066", "amber"),  # 340°
     ("#00cc44", "mint"), ("#00ccff", "mint"),
     ("#2a4bff", "aurora"), ("#8a2be2", "aurora"), ("#cc22cc", "aurora")],
)
def test_custom_colour_picks_family_by_hue(main, family):
    palette = branding.theme().derive_palette(BrandColours(main, "#ffb020"))
    assert branding.logo_family("custom", palette) == family


def test_every_preset_the_theme_offers_has_a_family():
    assert set(branding.theme().palettes()) <= set(branding.PRESET_FAMILY)


def test_default_logo_urls_follow_the_palette(db):
    # set the global palette to red_plum with the existing helper used in this file's other tests
    ...
```

Replace the last test's body with the existing settings helper used elsewhere in `tests/domain/test_branding.py` (search `color_palette` there) and assert:

```python
    b = branding.resolve(None, "cs")
    assert b.logo_url == "/assets/logo-amber-bar.svg"
    assert b.hero_logo_url == "/assets/logo-amber-hero-light.svg"
    assert b.hero_logo_dark_url == "/assets/logo-amber-hero-dark.svg"
    assert b.logo_family == "amber"


def test_uploaded_hero_logo_is_not_replaced_and_has_no_dark_twin(db):
    branding.set_hero_logo(None, png_bytes(), admin_id=ADMIN_ID)   # helpers exist in this module
    b = branding.resolve(None, "cs")
    assert b.hero_logo_url.startswith("/media/") and b.hero_logo_dark_url is None
    assert b.logo_url.endswith("-bar.svg")                         # bar untouched
```

Hue note: the derived `main` can be darkened for contrast, but its hue stays within a few degrees; the test hexes are chosen away from the 70/200/330 boundaries. Verify each with `colorsys.rgb_to_hls` before committing.

- [ ] **Step 2:** `uv run pytest tests/domain/test_branding.py -k "family or logo" -v` → FAIL (`AttributeError`).
- [ ] **Step 3: Implement.** Replace `DEFAULT_LOGO` / `DEFAULT_HERO_LOGO` and add:

```python
import colorsys

LOGO_FAMILIES = ("aurora", "mint", "amber")
PRESET_FAMILY = {
    "indigo_pink": "aurora",
    "violet_white": "aurora",
    "blue_teal": "mint",
    "green_blue": "mint",
    "red_plum": "amber",
}


def _asset(family: str, kind: str) -> str:
    return f"/assets/logo-{family}-{kind}.svg"


def logo_family(palette: str, custom: DerivedPalette | None) -> str:
    """Which built-in logo goes with a palette; a custom palette by the hue of its main colour."""
    if palette != CUSTOM_PALETTE or custom is None:
        return PRESET_FAMILY[palette]
    value = custom.main.lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    hue = colorsys.rgb_to_hls(red, green, blue)[0] * 360
    if hue < 70 or hue >= 330:
        return "amber"
    return "mint" if hue < 200 else "aurora"
```

In `Branding` add `hero_logo_dark_url: str | None` and `logo_family: str`. In `resolve()`: move the palette/custom block **above** the logo block, compute `family = logo_family(palette, custom)`, then:

```python
    logo_url, sources["logo"] = _asset(family, "bar"), "default"
    ...                                   # existing loop for uploaded logo unchanged
    hero_logo_url, sources["hero_logo"] = _asset(family, "hero-light"), "default"
    hero_logo_dark_url: str | None = _asset(family, "hero-dark")
    for source, row in levels:
        entry = _asset_entry(row, "hero_logo")
        if entry and entry["asset"]:
            hero_logo_url, sources["hero_logo"] = reverse("media", args=[entry["asset"]]), source
            hero_logo_dark_url = None
            break
```

Pass the new fields to `Branding(...)`. If `palette` is not in `PRESET_FAMILY` (a preset added without a family) the `test_every_preset...` test fails first; do not add a silent fallback.

- [ ] **Step 4:** run → PASS; also `uv run pytest tests/domain -q`.
- [ ] **Step 5: Commit** `feat(branding): logo family from palette`.

---

### Task 3: Templates, plate and pictures

**Files:**
- Create: `app/api/jinja2/public/_hero_logo.html`
- Modify: `app/api/jinja2/public/landing.html:4`, `about.html:4`, `app/plugins/theme_default/jinja2/theme_default/layout.html:39`, `app/plugins/theme_default/assets/theme.css` (after `.about-logo-centered`, ~line 385)
- Test: `tests/api/test_branding_pages.py:137-160`, `tests/api/test_public_layout.py:210-230`

**Interfaces:**
- Consumes: `branding.hero_logo_url`, `branding.hero_logo_dark_url`, `branding.name`.
- Produces: markup `<div class="hero-logo-plate"><picture>…<img class="about-logo about-logo-centered" …></picture></div>`.

- [ ] **Step 1: Update failing tests.** In `test_branding_pages.py` replace `/assets/logo.png` with `/assets/logo-blue-…`: the default palette is `blue_teal` → family `mint`:

```python
BAR = r'<img class="site-logo" src="/assets/logo-mint-bar\.svg" alt=""'

def test_logo_next_to_the_name_has_an_empty_alt(client):
    assert re.search(BAR, text(client.get("/")))


def test_landing_hero_uses_a_picture_on_a_plate(client):
    html = text(client.get("/"))
    assert 'class="hero-logo-plate"' in html
    assert re.search(
        r'<picture>\s*<source media="\(prefers-color-scheme: dark\)" '
        r'srcset="/assets/logo-mint-hero-dark\.svg">\s*'
        r'<img class="about-logo about-logo-centered" src="/assets/logo-mint-hero-light\.svg"',
        html,
    )


def test_hero_with_an_uploaded_logo_has_no_dark_source_but_keeps_the_plate():
    branding.set_hero_logo(None, png_bytes(), admin_id=ADMIN_ID)
    html = text(Client().get("/"))
    assert 'class="hero-logo-plate"' in html and "<source" not in html
    assert re.search(BAR, html)                       # bar logo untouched


def test_bar_logo_follows_a_custom_palette(client):
    # custom palette with an amber main (#ff6a00) via the helper `brand(...)` in this module
    ...
```

Fill the last test with the module's `brand(None, custom=True)` helper if its colours are amber; otherwise set the palette with the helper that writes `tokens_json` (look at `brand()` lines 35–50) and assert `logo-amber-bar.svg`. In `test_public_layout.py` update `test_bar_shows_the_logo` regex to `logo-mint-bar\.svg` and keep the two centred/large tests (class names stay).

- [ ] **Step 2:** `uv run pytest tests/api/test_branding_pages.py tests/api/test_public_layout.py -q` → FAIL.
- [ ] **Step 3: Implement.**

`_hero_logo.html` (size passed with `{% with %}`; alt only where the page has no heading with the name):

```jinja
{# `width`, `height`, `alt` set by the includer. The plate keeps the logo readable on any page colour. #}
<div class="hero-logo-plate">
  <picture>
    {% if branding.hero_logo_dark_url %}<source media="(prefers-color-scheme: dark)" srcset="{{ branding.hero_logo_dark_url }}">{% endif %}
    <img class="about-logo about-logo-centered" src="{{ branding.hero_logo_url }}" alt="{{ alt }}" width="{{ width }}" height="{{ height }}">
  </picture>
</div>
```

`landing.html:4` → `{% with width=144, height=100, alt="" %}{% include "public/_hero_logo.html" %}{% endwith %}`.
`about.html:4` → `<div class="hero">{% with width=240, height=166, alt=branding.name %}{% include "public/_hero_logo.html" %}{% endwith %}<h1>…</h1></div>`. The old about page hard-coded `/assets/logo-full.svg`; it now uses the resolved hero logo, which also fixes that a quiz-level hero logo was ignored there. Check that `branding` is in the `about` template context (it is in the layout; if not, add it in the `about` view the same way `landing` gets it) and keep `alt` = the former `"Kvízotron"` only when `branding.name` is the default.

`layout.html:39` stays (`src="{{ branding.logo_url }}"`), no change needed.

`theme.css`:

```css
/* The hero logo sits on the card colour so that it reads on any page colour and in both modes. */
.hero-logo-plate {
  width: fit-content;
  margin: 0 auto 1rem;
  padding: 0.75rem 1.25rem;
  border-radius: 1rem;
  background: var(--kvz-card);
}

.hero-logo-plate .about-logo {
  margin-bottom: 0;
}
```

Note the CSP: no inline style added, so no nonce is needed.

- [ ] **Step 4:** run both files → PASS; then `uv run pytest tests/api -q` for regressions (other tests may reference old URLs: `grep -rn "assets/logo\.\(png\|svg\)\|logo-full" tests app` must return nothing).
- [ ] **Step 5: Commit** `feat(branding): hero logo on a plate with light and dark drawing`.

---

### Task 4: Admin preview

**Files:**
- Modify: `app/api/jinja2/admin/_branding_fields.html` (top of the `<section>`), and the context providers: `admin_settings.settings_page` and `admin_quizzes.settings_page` (find with `grep -n "branding_group" app/api/*.py`)
- Test: `tests/api/test_admin_branding.py`

**Interfaces:**
- Consumes: `branding.resolve(quiz, locale)`; fields `.logo_url`, `.hero_logo_url`, `.hero_logo_dark_url`, `.logo_family`, `.sources`.
- Produces: context variable `logo_preview` = the `Branding` object.

- [ ] **Step 1: Failing test**

```python
def test_global_settings_page_previews_the_builtin_logo(admin_client):
    html = admin_client.get("/admin/settings/").text   # use the URL helper already used in this module
    assert 'class="logo-preview"' in html and "logo-mint-bar.svg" in html
    assert "Built-in logo" in html


def test_preview_is_replaced_by_a_note_when_a_logo_is_uploaded(admin_client):
    branding.set_logo(None, png_bytes(), admin_id=ADMIN_ID)
    html = admin_client.get("/admin/settings/").text
    assert 'class="logo-preview"' in html and "logo-mint-bar.svg" not in html
```

- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.** In both `settings_page` functions add `logo_preview=branding.resolve(quiz_or_None, locale)` to the context (`locale` as the neighbouring code already obtains it). In the template, below the `<p>` intro:

```jinja
{% if logo_preview %}
<p class="logo-preview">
  <img src="{{ logo_preview.logo_url }}" alt="" width="32" height="32">
  {% if logo_preview.sources["logo"] == "default" %}
  {{ _("Built-in logo (%(family)s), chosen by the colour palette.", family=logo_preview.logo_family) }}
  {% else %}{{ _("A custom logo is used for the bar.") }}{% endif %}
</p>
{% endif %}
```

The second test only needs the media URL instead of the built-in one; `logo-mint-bar.svg` must be absent. Add a `.logo-preview img { vertical-align: middle; }` rule if the image sits badly (check in Task 5).

Then `make messages`, fill cs and uk translations for the two new strings (en is the msgid), re-run `make messages`.

- [ ] **Step 4:** `uv run pytest tests/api/test_admin_branding.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(branding): admin shows which built-in logo applies`.

---

### Task 5: Docs, browser check, quality

**Files:**
- Modify: `docs/_architecture/adr/0054-branding-owned-by-domain-and-theme.md` (line 34 "the logo `/assets/logo.svg`"; add an addendum 2026-11-11), `docs/_architecture/acceptance-criteria.md`, `docs/_architecture/README.md` only if an index range changes (`tests/test_docs.py` guards it).

- [ ] **Step 1:** Edit ADR-0054: built-in logo is one of three families chosen by palette; add the addendum with decisions 1–4 and the reason (a logo cannot be chosen for an arbitrary page colour, so contrast is guaranteed by layout). Do not renumber IDs. Add one AC (next free number) "built-in logo follows the palette, readable on any colour" and name the tests of Tasks 2–3 in it (AC tests are named by convention; check how AC-128 is referenced).
- [ ] **Step 2:** `make quality` → all green (lint, tests, gitleaks, tech-debt check).
- [ ] **Step 3: Browser walkthrough** (`kvizotron-browser-walkthrough`, keep stack data): with a throwaway quiz verify, in light **and** dark OS mode, at 390 px and desktop width: (a) each of the five presets and a custom palette with a bright yellow main (`#ffe600`), a mid blue (`#1769e0`) and a very dark main (`#101830`): bar logo visible, hero logo plate visible, text readable; (b) quiz-level uploaded logo shows with no `<source>`; (c) admin settings page preview. Record anything off as a fix, not as tech debt.
- [ ] **Step 4:** `make smoke`.
- [ ] **Step 5: Commit** `docs(branding): ADR-0054 addendum and AC for built-in logo families`.

## Self-Review

- Spec coverage: families by palette (T2), bar dark mark (T1/T3), hero full on plate with light/dark (T3), custom hue mapping (T2), uploaded logo untouched (T2/T3 tests), admin preview (T4), docs (T5), favicon explicitly out of scope.
- Known open item for the implementer, not a placeholder: `kvizotron_v4/` and `tmp-old/` stay untracked and are not part of any commit; the pre-existing uncommitted `logo.svg`/`logo-full.svg`/`logo.png` changes are superseded by Task 1 (confirm with the user before deleting `logo.svg`, it is not ours).
- Type consistency: `logo_family` (function and `Branding` field), `hero_logo_dark_url`, `PRESET_FAMILY` used identically in Tasks 2–4.

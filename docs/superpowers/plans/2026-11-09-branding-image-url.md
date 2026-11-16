# Branding images from a URL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin set the branding `logo` and `hero_logo` from a URL, at both the global and
the quiz level, with the same fetch and validation the question editor already uses for images
(ADR-0043), always kept as a local copy.

**Architecture:** `app/domain/branding.py` gains two small additions to its existing asset-replacement
machinery: a shape change so `assets_json` can carry the address an asset came from, and two new
functions (`fetch_asset_address`, `set_asset`) that let the API layer fetch an address and then point
a field at the result, the same two-step shape `app/api/admin_quizzes.py` already uses for questions.
`BrandingForm` (`app/api/admin_forms.py`) gains a URL field per image and resolves both addresses
before touching anything else, so a refused address blocks the save instead of partially applying it.

**Tech Stack:** Django forms, the existing `MediaStorageProvider` contract
(`app/providers/media_local/provider.py`), pytest + `pytest-django`, `monkeypatch` over
`app.providers.media_local.remote.fetch` for tests (no real network).

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-11-09-branding-image-url-design.md`. Follow it;
  this plan also makes a few implementation-level calls not spelled out there (noted inline as
  **[plan]**) that do not change any goal, non-goal or behaviour in the spec.
- Reuses `check_image_address`/`fetch_image` from `app/providers/media_local/provider.py` unchanged. No
  new provider method, no new setting, no "external" mode for branding.
- No new database column or migration: `assets_json` is already a `JSONField`; its value shape changes
  from a plain string to `{"asset": str, "source": str | None}`, read back-compatibly for existing rows.
- Every new admin-facing string uses `gettext_lazy`, like the rest of `admin_forms.py`.
- `make test` must pass after every task; `make quality` must pass before the final commit.

---

## File Structure

| File | Change |
|---|---|
| `app/domain/branding.py` | Asset storage becomes `{"asset", "source"}` (back-compatible); add `fetch_asset_address`, `set_asset`, `logo_source`, `hero_logo_source` |
| `app/api/admin_forms.py` | `BrandingForm` gains `logo_source`/`hero_logo_source` fields; `save()` resolves addresses before persisting anything |
| `app/api/admin_branding.py` | `_save()`'s exception handling simplifies now that `BrandingForm.save()` blames the right field itself |
| `app/api/admin_view.py` | `BRANDING_PLACES` and `branding_group`'s `differs()` learn the two new field names |
| `tests/domain/test_branding.py` | New tests for the shape change and the two new domain functions |
| `tests/api/test_admin_branding.py` | New end-to-end tests posting `logo_source`/`hero_logo_source` to the real admin views |
| `docs/_architecture/acceptance-criteria.md` | New `AC-128` row |
| `docs/_architecture/modules/api-ui.md` | One clause added to the existing branding row of the "Where things are set" table |
| `app/api/locale/*/LC_MESSAGES/django.po` (+ `.mo`) | New strings translated, via `make messages` |

No template changes: `app/api/jinja2/admin/_branding_fields.html` already renders every `BrandingForm`
field generically through `field.as_field_group()`; a new form field appears automatically once it is
placed in `admin_view.BRANDING_PLACES`.

---

### Task 1: `assets_json` carries an optional source address

**Files:**
- Modify: `app/domain/branding.py:126-137` (`_has_asset`, `has_logo`, `has_hero_logo`), `app/domain/branding.py:147-197` (`resolve`, the two logo/hero_logo lookup loops), `app/domain/branding.py:281-303` (`_unused`, `_replace_asset`)
- Test: `tests/domain/test_branding.py`

**Interfaces:**
- Produces: `_asset_entry(row: BrandingConfiguration | None, field: str) -> dict[str, str | None] | None`
  — `{"asset": <id>, "source": <url> | None}`, or `None` if the field has no asset. Reads a legacy
  plain-string value as `{"asset": value, "source": None}`. Internal (`_`-prefixed), used only within
  `branding.py`.
- Produces: `_asset_ids(assets_json: Mapping[str, object]) -> set[str]` — every asset id referenced by
  a row's `assets_json`, whichever shape each value is in. Internal, replaces the old
  `asset_id in row.assets_json.values()` check in `_unused`.
- `has_logo`, `has_hero_logo`, `resolve` keep their existing public signatures; only their bodies
  change.

- [ ] **Step 1: Write the failing tests**

Add to `tests/domain/test_branding.py` (needs no new imports — `BrandingConfiguration` is already
imported):

```python
def test_an_uploaded_logo_is_stored_with_no_source():
    """A plain upload has no address to remember."""
    quiz = make_quiz()
    branding.set_logo(quiz, png(), admin_id=ADMIN_ID)
    row = BrandingConfiguration.objects.get(quiz=quiz)
    assert row.assets_json["logo"]["asset"]
    assert row.assets_json["logo"]["source"] is None


def test_a_legacy_plain_string_asset_still_resolves():
    """A row written before this change stores a plain string, not a dict."""
    quiz = make_quiz()
    asset_id = branding.media().store_image(png())
    BrandingConfiguration.objects.create(
        quiz=quiz, theme_id="default", assets_json={"logo": asset_id}
    )
    assert branding.has_logo(quiz)
    assert branding.resolve(quiz, "cs").logo_url == f"/media/{asset_id}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/domain/test_branding.py -k legacy_plain_string or uploaded_logo_is_stored"`

Actually use the plain pytest invocation this project's `make test` wraps:

Run: `uv run pytest tests/domain/test_branding.py -k "legacy_plain_string or uploaded_logo_is_stored" -v`

Expected: `test_an_uploaded_logo_is_stored_with_no_source` FAILS — `row.assets_json["logo"]` is a plain
string today, so `["asset"]` raises `TypeError`. `test_a_legacy_plain_string_asset_still_resolves`
currently PASSES already (today's code only ever reads plain strings) — that is fine, it becomes the
regression guard for Step 3.

- [ ] **Step 3: Implement the shape change**

In `app/domain/branding.py`, replace the block from `_has_asset` through `has_hero_logo`
(current lines 126-137):

```python
def _asset_entry(row: BrandingConfiguration | None, field: str) -> dict[str, str | None] | None:
    """Reads `assets_json[field]`, as the new `{asset, source}` shape or the old plain string."""
    raw = row.assets_json.get(field) if row else None
    if raw is None:
        return None
    if isinstance(raw, str):
        return {"asset": raw, "source": None}
    return {"asset": raw.get("asset"), "source": raw.get("source")}


def _has_asset(quiz: Quiz | None, field: str) -> bool:
    entry = _asset_entry(_row(quiz), field)
    return bool(entry and entry["asset"])


def has_logo(quiz: Quiz | None) -> bool:
    return _has_asset(quiz, "logo")


def has_hero_logo(quiz: Quiz | None) -> bool:
    return _has_asset(quiz, "hero_logo")
```

In `resolve`, replace the two lookup loops (current lines 165-176):

```python
    logo_url, sources["logo"] = DEFAULT_LOGO, "default"
    for source, row in levels:
        entry = _asset_entry(row, "logo")
        if entry:
            logo_url, sources["logo"] = reverse("media", args=[entry["asset"]]), source
            break
    hero_logo_url, sources["hero_logo"] = DEFAULT_HERO_LOGO, "default"
    for source, row in levels:
        entry = _asset_entry(row, "hero_logo")
        if entry:
            hero_logo_url, sources["hero_logo"] = reverse("media", args=[entry["asset"]]), source
            break
```

Replace `_unused` (current lines 281-284):

```python
def _asset_ids(assets_json: Mapping[str, object]) -> set[str]:
    ids: set[str] = set()
    for value in assets_json.values():
        if isinstance(value, str):
            ids.add(value)
        elif isinstance(value, dict) and value.get("asset"):
            ids.add(cast(str, value["asset"]))
    return ids


def _unused(asset_id: str) -> bool:
    return not any(
        asset_id in _asset_ids(row.assets_json) for row in BrandingConfiguration.objects.all()
    )
```

In `_replace_asset` (current lines 287-297), change the body that reads the old id and writes the new
one:

```python
def _replace_asset(
    quiz: Quiz | None, field: str, asset_id: str | None, admin_id: str, *, source: str | None = None
) -> None:
    with transaction.atomic():
        _editable(quiz)
        row = _row(quiz)
        assets = dict(row.assets_json) if row else {}
        old_entry = _asset_entry(row, field)
        old = old_entry["asset"] if old_entry else None
        if asset_id:
            assets[field] = {"asset": asset_id, "source": source}
        else:
            assets.pop(field, None)
        _save(quiz, field, admin_id, assets_json=assets)
    if old and old != asset_id and _unused(old):
        try:
            media().delete_image(old)
        except Exception:  # the change is saved; a file left behind is no reason to fail it
            logger.exception("Could not delete a replaced %s file", field)
```

`_set_asset` (upload path) needs no change: it already calls `_replace_asset(quiz, field, asset_id,
admin_id)` with no `source`, which now defaults to `None`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/domain/test_branding.py -v`

Expected: PASS, including every pre-existing test in the file (`test_replaced_logo_deletes_the_old_asset`,
`test_shared_asset_is_kept`, `test_refused_logo_changes_nothing`, etc.) — the shape change must not
break any of them, since they all go through `set_logo`/`remove_logo`/`has_logo`, not the raw JSON.

- [ ] **Step 5: Run the wider domain and contracts test suites**

Run: `uv run pytest tests/domain/ tests/contracts/ tests/test_wiring.py -v`

Expected: PASS. This catches any other reader of `BrandingConfiguration.assets_json` this plan missed.

- [ ] **Step 6: Commit**

```bash
git add app/domain/branding.py tests/domain/test_branding.py
git commit -m "$(cat <<'EOF'
refactor(branding): store an asset's source address alongside its id

assets_json values become {asset, source} instead of a plain asset id,
read back-compatibly, to make room for images set by address.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Fetch an address and point a field at it

**Files:**
- Modify: `app/domain/branding.py` (new functions, placed after `set_hero_logo`/`remove_hero_logo`
  and before `set_colours`)
- Test: `tests/domain/test_branding.py`

**Interfaces:**
- Consumes: `_asset_entry`, `_unused`, `_replace_asset`, `media()` from Task 1; `settings.internal_addresses_allowed() -> bool` (`app/domain/settings.py:477`); `MediaStorageProvider.check_image_address(url: str) -> None` and `.fetch_image(url: str, *, allow_internal: bool, deadline: float) -> str` (`app/contracts/__init__.py:424-426`).
- Produces: `fetch_asset_address(url: str, *, deadline: float) -> str` — raises `ImageAddressInvalid`
  or `ImageRefused` (`app/contracts/__init__.py:141,151`); returns a stored asset id on success.
- Produces: `set_asset(quiz: Quiz | None, field: str, *, asset_id: str, source: str | None, admin_id: str) -> None` — raises `ValueError` for a `field` other than `"logo"`/`"hero_logo"`; otherwise behaves like `set_logo`/`set_hero_logo` (editable check, audit, old-asset cleanup) but takes an already-stored asset id instead of raw bytes.
- Produces: `logo_source(quiz: Quiz | None) -> str | None`, `hero_logo_source(quiz: Quiz | None) -> str | None` — the address the field's current image was fetched from, or `None` for an upload or no image. Used by `BrandingForm` in Task 3 to prefill the URL input and to decide whether a submitted address is unchanged.

- [ ] **Step 1: Write the failing tests**

Add near the top of `tests/domain/test_branding.py`, after the existing imports, the mocking
infrastructure this task needs (mirrors `tests/api/test_external_images.py`):

```python
from unittest import mock

from app.providers.media_local import remote
```

and change the existing `from app.contracts import COLOR_PALETTE, CUSTOM_PALETTE, BrandColours,
ImageRefused` line to also import `ImageAddressInvalid`:

```python
from app.contracts import COLOR_PALETTE, CUSTOM_PALETTE, BrandColours, ImageAddressInvalid, ImageRefused
```

Add fixtures and tests:

```python
@pytest.fixture
def fetch(monkeypatch):
    fake = mock.Mock(side_effect=lambda *a, **k: png())
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


@pytest.fixture
def down(monkeypatch):
    fake = mock.Mock(side_effect=remote.RemoteRefused("down"))
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


def test_fetch_asset_address_stores_a_copy(fetch):
    asset_id = branding.fetch_asset_address("https://logos.example/a.png", deadline=_soon())
    assert exists(asset_id)


def test_fetch_asset_address_rejects_a_malformed_address():
    with pytest.raises(ImageAddressInvalid):
        branding.fetch_asset_address("ftp://logos.example/a.png", deadline=_soon())


def test_fetch_asset_address_rejects_an_unfetchable_address(down):
    with pytest.raises(ImageRefused):
        branding.fetch_asset_address("https://logos.example/a.png", deadline=_soon())


def test_set_asset_stores_the_source_and_resolves_the_url(fetch):
    quiz = make_quiz()
    asset_id = branding.fetch_asset_address("https://logos.example/a.png", deadline=_soon())
    branding.set_asset(
        quiz, "logo", asset_id=asset_id, source="https://logos.example/a.png", admin_id=ADMIN_ID
    )
    assert branding.logo_source(quiz) == "https://logos.example/a.png"
    assert branding.resolve(quiz, "cs").logo_url == f"/media/{asset_id}"


def test_set_asset_replacing_an_address_based_logo_deletes_the_old_one(fetch):
    quiz = make_quiz()
    first = branding.fetch_asset_address("https://logos.example/a.png", deadline=_soon())
    branding.set_asset(quiz, "logo", asset_id=first, source="https://logos.example/a.png", admin_id=ADMIN_ID)
    second = branding.fetch_asset_address("https://logos.example/b.png", deadline=_soon())
    branding.set_asset(quiz, "logo", asset_id=second, source="https://logos.example/b.png", admin_id=ADMIN_ID)
    assert not exists(first)
    assert branding.logo_source(quiz) == "https://logos.example/b.png"


def test_set_asset_rejects_an_unknown_field():
    with pytest.raises(ValueError):
        branding.set_asset(None, "wrong", asset_id="x", source=None, admin_id=ADMIN_ID)


def test_logo_source_is_none_without_an_image():
    assert branding.logo_source(None) is None
    assert branding.hero_logo_source(None) is None
```

Add the small time helper these tests use, next to the existing `png()`/`asset_of()`/`exists()`
helpers:

```python
import time
```

(add this import at the top of the file, next to `import io`)

```python
def _soon():
    return time.monotonic() + 5.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/domain/test_branding.py -k "fetch_asset_address or set_asset or logo_source" -v`

Expected: every new test FAILS with `AttributeError: module 'app.domain.branding' has no attribute
'fetch_asset_address'` (or `set_asset`, `logo_source`, `hero_logo_source`).

- [ ] **Step 3: Implement the two functions**

In `app/domain/branding.py`, add after `remove_hero_logo` (current line 330) and before
`set_colours`:

```python
def _asset_source(quiz: Quiz | None, field: str) -> str | None:
    entry = _asset_entry(_row(quiz), field)
    return entry["source"] if entry else None


def logo_source(quiz: Quiz | None) -> str | None:
    return _asset_source(quiz, "logo")


def hero_logo_source(quiz: Quiz | None) -> str | None:
    return _asset_source(quiz, "hero_logo")


def fetch_asset_address(url: str, *, deadline: float) -> str:
    """Raises `ImageAddressInvalid`/`ImageRefused`. The image is stored like an upload would be."""
    storage = media()
    storage.check_image_address(url)
    return storage.fetch_image(
        url, allow_internal=settings.internal_addresses_allowed(), deadline=deadline
    )


def set_asset(
    quiz: Quiz | None, field: str, *, asset_id: str, source: str | None, admin_id: str
) -> None:
    """Points `field` (logo or hero_logo) at an already-stored asset, such as a fetched address."""
    if field not in ("logo", "hero_logo"):
        raise ValueError(field)
    try:
        _replace_asset(quiz, field, asset_id, admin_id, source=source)
    except Exception:
        if _unused(asset_id):
            media().delete_image(asset_id)
        raise
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/domain/test_branding.py -v`

Expected: PASS, all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add app/domain/branding.py tests/domain/test_branding.py
git commit -m "$(cat <<'EOF'
feat(branding): fetch a logo or hero logo from an address

Adds fetch_asset_address and set_asset, reusing the question editor's
address validation and fetch (ADR-0043). Not yet reachable from the
admin forms.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Wire the address field into `BrandingForm` and the admin views

**Files:**
- Modify: `app/api/admin_forms.py:1-35` (imports), `app/api/admin_forms.py:792-870` (`BrandingForm`)
- Modify: `app/api/admin_branding.py:36-42` (`_save`'s exception handling)
- Modify: `app/api/admin_view.py:108-119` (`BRANDING_PLACES`), `app/api/admin_view.py:131-144` (`branding_group`'s `differs`)
- Test: `tests/api/test_admin_branding.py`

**Interfaces:**
- Consumes: `branding.logo_source`, `branding.hero_logo_source`, `branding.fetch_asset_address`,
  `branding.set_asset`, `branding.has_logo`, `branding.has_hero_logo`, `branding.set_logo`,
  `branding.set_hero_logo`, `branding.remove_logo`, `branding.remove_hero_logo` — all from Tasks 1-2.
  `app.contracts.ImageRefused` (also covers `ImageAddressInvalid`, its subclass).
- Produces: `BrandingForm` fields `logo_source`, `hero_logo_source` (both `forms.URLField`, optional),
  alongside the existing `logo`, `remove_logo`, `hero_logo`, `remove_hero_logo`.
- `BrandingForm.save(admin_id: str) -> None` keeps its existing signature and still raises
  `ImageRefused` on any image problem, but now also attributes the error to the right field itself
  (`self.add_error(...)`) before raising, for both the upload and the address path. `admin_branding.py`
  no longer needs to guess which field failed.

- [ ] **Step 1: Write the failing tests**

Add to `tests/api/test_admin_branding.py`. First, the imports and helpers it needs — change the
existing `from app.domain.models import BrandingConfiguration, QuizRevision` import is unaffected; add
near the top of the file:

```python
from unittest import mock

from app.providers.media_local import remote
```

and a raw-bytes PNG helper next to the existing `png()` (which returns a `SimpleUploadedFile` for
multipart uploads — keep it, add this one alongside it):

```python
def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 10, 10)).save(buffer, "PNG")
    return buffer.getvalue()
```

Fixtures, next to the existing `uploading` fixture:

```python
URL = "https://logos.example/a.png"
OTHER_URL = "https://logos.example/b.png"


@pytest.fixture
def fetch(monkeypatch):
    fake = mock.Mock(side_effect=lambda *a, **k: png_bytes())
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


@pytest.fixture
def down(monkeypatch):
    fake = mock.Mock(side_effect=remote.RemoteRefused("down"))
    monkeypatch.setattr(remote, "fetch", fake)
    return fake
```

Tests:

```python
def test_a_logo_address_is_fetched_and_removed(uploading, fetch):
    assert uploading.post(GLOBAL, {"logo_source": URL}).status_code == 302
    fetch.assert_called_once()
    assert branding.resolve(None, "cs").logo_url.startswith("/media/")
    assert branding.logo_source(None) == URL
    assert uploading.post(GLOBAL, {"remove_logo": "on"}).status_code == 302
    assert branding.resolve(None, "cs").logo_url == "/assets/logo.png"


def test_an_unchanged_logo_address_is_not_refetched(uploading, fetch):
    uploading.post(GLOBAL, {"logo_source": URL})
    fetch.reset_mock()
    response = uploading.post(GLOBAL, {"logo_source": URL, "name_cs": "Moje škola"})
    assert response.status_code == 302
    fetch.assert_not_called()


def test_a_changed_logo_address_is_refetched(uploading, fetch):
    uploading.post(GLOBAL, {"logo_source": URL})
    fetch.reset_mock()
    assert uploading.post(GLOBAL, {"logo_source": OTHER_URL}).status_code == 302
    fetch.assert_called_once()
    assert branding.logo_source(None) == OTHER_URL


def test_a_file_wins_over_a_logo_address_in_the_same_submit(uploading, fetch):
    uploading.post(GLOBAL, {"logo": png(), "logo_source": URL})
    fetch.assert_not_called()
    assert branding.logo_source(None) is None
    assert branding.resolve(None, "cs").logo_url.startswith("/media/")


def test_a_malformed_logo_address_is_refused_and_nothing_else_saves(uploading):
    response = uploading.post(
        GLOBAL, {"logo_source": "ftp://logos.example/a.png", "name_cs": "Moje škola"}
    )
    assert response.status_code == 200
    assert "ftp://logos.example/a.png" in text(response)
    assert not BrandingConfiguration.objects.exists()


def test_an_unreachable_logo_address_is_refused(uploading, down):
    response = uploading.post(GLOBAL, {"logo_source": URL})
    assert response.status_code == 200
    assert not BrandingConfiguration.objects.exists()


def test_a_hero_logo_address_is_independent_of_the_logo(uploading, fetch):
    assert uploading.post(GLOBAL, {"hero_logo_source": URL}).status_code == 302
    result = branding.resolve(None, "cs")
    assert result.hero_logo_url.startswith("/media/")
    assert result.logo_url == "/assets/logo.png"


def test_a_quiz_logo_address_overrides_the_global_one(uploading, fetch):
    quiz = make_quiz()
    assert uploading.post(quiz_url(quiz), {"logo_source": URL}).status_code == 302
    assert branding.resolve(quiz, "cs").logo_url.startswith("/media/")
    assert branding.resolve(None, "cs").logo_url == "/assets/logo.png"


def test_the_settings_page_renders_the_address_fields(showing_all):
    html = text(showing_all.get("/admin/settings"))
    assert 'name="logo_source"' in html
    assert 'name="hero_logo_source"' in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_admin_branding.py -k "address or logo_address" -v`

Expected: every new test FAILS — `BrandingForm` has no `logo_source`/`hero_logo_source` field yet, so
Django silently ignores the POST key and nothing changes (`fetch.assert_called_once()` fails, the
settings page has no such input, etc.).

- [ ] **Step 3: Add the fields and rewrite `save()` in `app/api/admin_forms.py`**

In the import block (current lines 1-35), add `import time` as the first import, and add
`ImageRefused` to the `app.contracts` import list (alphabetically between `BrandColours` and
`QuestionTypePlugin`):

```python
import time
from collections.abc import Mapping, Sequence
from typing import Any, cast

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.utils.text import format_lazy
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from app.api.i18n import PUBLIC_LOCALES
from app.contracts import (
    COLOR_PALETTE,
    CUSTOM_PALETTE,
    PARTICIPANT_KEYS,
    RESULT_KEYS,
    REWARD_RUN_KEYS,
    SCOREBOARD_UNNAMED,
    SCOREBOARD_VISIBILITY,
    BrandColours,
    ImageRefused,
    QuestionTypePlugin,
)
```

Immediately before `class BrandingForm(forms.Form):` (current line 792), add:

```python
FETCHES_SECONDS = 25.0  # all address fetches of one branding save, together
```

Replace the `if "logo" in allowed:` / `if "hero_logo" in allowed:` block inside `__init__` (current
lines 832-847) with:

```python
        if "logo" in allowed:
            self.fields["logo"] = forms.FileField(label=gettext_lazy("Logo"), required=False)
            self.fields["logo_source"] = forms.URLField(
                label=gettext_lazy("Or a logo address"),
                required=False,
                max_length=2000,
                initial=branding.logo_source(quiz) or "",
                help_text=gettext_lazy(
                    "Fetched and kept as a copy when you save. Participants never see the address."
                ),
            )
            self.fields["remove_logo"] = forms.BooleanField(
                label=gettext_lazy("Remove the logo"), required=False
            )
        if "hero_logo" in allowed:
            self.fields["hero_logo"] = forms.FileField(
                label=gettext_lazy("Landing page logo"),
                required=False,
                help_text=gettext_lazy(
                    "Shown large and centred on the home page. Empty: the built-in logo."
                ),
            )
            self.fields["hero_logo_source"] = forms.URLField(
                label=gettext_lazy("Or a landing page logo address"),
                required=False,
                max_length=2000,
                initial=branding.hero_logo_source(quiz) or "",
                help_text=gettext_lazy(
                    "Fetched and kept as a copy when you save. Participants never see the address."
                ),
            )
            self.fields["remove_hero_logo"] = forms.BooleanField(
                label=gettext_lazy("Remove the landing page logo"), required=False
            )
```

Replace `save()` (current lines 849-860) with:

```python
    def save(self, admin_id: str) -> None:
        """Raises `ImageRefused`, with the field already blamed, before anything else changes."""
        deadline = time.monotonic() + FETCHES_SECONDS
        fetched: dict[str, str] = {}
        try:
            for field in ("logo", "hero_logo"):
                if field not in self.fields or self.cleaned_data.get(field):
                    continue  # no such image on this theme, or a file was uploaded and wins
                url = self.cleaned_data.get(f"{field}_source", "")
                if not url:
                    continue
                current = getattr(branding, f"{field}_source")(self.quiz)
                if url == current and getattr(branding, f"has_{field}")(self.quiz):
                    continue  # unchanged address with a copy already stored: nothing to do
                try:
                    fetched[field] = branding.fetch_asset_address(url, deadline=deadline)
                except ImageRefused as error:
                    self.add_error(f"{field}_source", str(error))
                    raise
        except ImageRefused:
            for asset_id in fetched.values():
                branding.media().delete_image(asset_id)
            raise
        upload = self.cleaned_data.get("logo")
        if upload:
            try:
                branding.set_logo(self.quiz, upload.read(), admin_id=admin_id)
            except ImageRefused as error:
                self.add_error("logo", f"{upload.name}: {error}")
                raise
        elif "logo" in fetched:
            branding.set_asset(
                self.quiz,
                "logo",
                asset_id=fetched["logo"],
                source=self.cleaned_data["logo_source"],
                admin_id=admin_id,
            )
        elif self.cleaned_data.get("remove_logo") and branding.has_logo(self.quiz):
            branding.remove_logo(self.quiz, admin_id=admin_id)
        hero_upload = self.cleaned_data.get("hero_logo")
        if hero_upload:
            try:
                branding.set_hero_logo(self.quiz, hero_upload.read(), admin_id=admin_id)
            except ImageRefused as error:
                self.add_error("hero_logo", f"{hero_upload.name}: {error}")
                raise
        elif "hero_logo" in fetched:
            branding.set_asset(
                self.quiz,
                "hero_logo",
                asset_id=fetched["hero_logo"],
                source=self.cleaned_data["hero_logo_source"],
                admin_id=admin_id,
            )
        elif self.cleaned_data.get("remove_hero_logo") and branding.has_hero_logo(self.quiz):
            branding.remove_hero_logo(self.quiz, admin_id=admin_id)
        stored = branding.texts_of(self.quiz)
        for name in self.text_fields:
            typed = {code: self.cleaned_data[f"{name}_{code}"].strip() for code in branding.LOCALES}
            typed = {code: text for code, text in typed.items() if text}
            if typed != stored.get(name, {}):
                branding.set_texts(self.quiz, name, typed, admin_id=admin_id)
        if branding.CONTACT_EMAIL in self.fields:
            email = self.cleaned_data[branding.CONTACT_EMAIL].strip()
            if email != stored.get(branding.CONTACT_EMAIL, {}).get("cs", ""):
                branding.set_contact_email(self.quiz, email, admin_id=admin_id)
```

- [ ] **Step 4: Simplify `admin_branding.py`'s exception handling**

In `app/api/admin_branding.py`, replace the `try`/`except` block inside `_save` (current lines 36-42):

```python
    form = BrandingForm(request.POST, request.FILES, quiz=quiz)
    if not form.is_valid():
        return form
    try:
        form.save(admin_id)
    except ImageRefused:
        return form
    return None
```

(The `field`/`name` lookup is gone — `BrandingForm.save()` now attributes the error itself.)

- [ ] **Step 5: Make the new fields render, in `app/api/admin_view.py`**

In `BRANDING_PLACES` (current lines 109-119), add the two new field names:

```python
BRANDING_PLACES = {
    f"{field}_{code}": ("look", BASIC if field == "name" else "advanced")
    for field in branding.TEXT_LIMITS
    for code in branding.LOCALES
} | {
    "contact_email": ("look", "advanced"),
    "logo": ("look", BASIC),
    "logo_source": ("look", BASIC),
    "remove_logo": ("look", BASIC),
    "hero_logo": ("look", BASIC),
    "hero_logo_source": ("look", BASIC),
    "remove_hero_logo": ("look", BASIC),
}
```

In `branding_group`'s inner `differs` function (current lines 131-144), extend the field-name mapping
so `logo_source`/`hero_logo_source` are recognised as part of the logo/hero_logo group instead of
falling into the `name.split("_")[0]` fallback (which would wrongly compute `"hero"` for
`hero_logo_source`):

```python
    def differs(name: str) -> bool:
        if name == "contact_email":
            field = "contact_email"
        elif name in ("logo", "logo_source", "remove_logo"):
            field = "logo"
        elif name in ("hero_logo", "hero_logo_source", "remove_hero_logo"):
            field = "hero_logo"
        else:
            field = name.split("_")[0]
        if field == "logo":
            return branding.has_logo(quiz)
        if field == "hero_logo":
            return branding.has_hero_logo(quiz)
        return bool(stored.get(field))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/api/test_admin_branding.py -v`

Expected: PASS, all tests in the file, including every pre-existing one (the `save()` rewrite must not
change behaviour for plain uploads, removals or unrelated text fields).

- [ ] **Step 7: Run the wider API test suite**

Run: `uv run pytest tests/api/ tests/test_wiring.py tests/test_layers.py -v`

Expected: PASS. `test_wiring.py` and `test_layers.py` catch an accidental cross-layer import or an
unreachable code path.

- [ ] **Step 8: Commit**

```bash
git add app/api/admin_forms.py app/api/admin_branding.py app/api/admin_view.py tests/api/test_admin_branding.py
git commit -m "$(cat <<'EOF'
feat(branding): set the logo and hero logo from an address

BrandingForm gains logo_source/hero_logo_source, fetched and validated
exactly like a question image's address (ADR-0043), always kept as a
local copy. Both addresses resolve before any field is saved, so a
refused one blocks the whole submit instead of partially applying it.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Translate the new strings

**Files:**
- Modify: `app/api/locale/cs/LC_MESSAGES/django.po`, `app/api/locale/uk/LC_MESSAGES/django.po` (+ the
  corresponding `.mo` files, which `make messages` compiles)

**Interfaces:**
- Consumes: the four new `gettext_lazy` strings added in Task 3 ("Or a logo address", "Or a landing
  page logo address", "Fetched and kept as a copy when you save. Participants never see the address.").

- [ ] **Step 1: Extract strings**

Run: `make messages`

This updates `app/api/locale/*/LC_MESSAGES/django.po` with new `msgid` entries (empty `msgstr`) for the
strings added in Task 3, and recompiles every `.mo` file.

- [ ] **Step 2: Fill in the Czech and Ukrainian translations**

Open `app/api/locale/cs/LC_MESSAGES/django.po` and `app/api/locale/uk/LC_MESSAGES/django.po`. For each
new empty `msgstr` next to the four new `msgid`s, write the translation. For example, in the `cs` file:

```po
msgid "Or a logo address"
msgstr "Nebo adresa loga"

msgid "Or a landing page logo address"
msgstr "Nebo adresa loga pro úvodní stránku"

msgid "Fetched and kept as a copy when you save. Participants never see the address."
msgstr "Při uložení se stáhne a uloží jako kopie. Účastníci adresu nikdy neuvidí."
```

(Match the exact `msgid` text `make messages` produced — copy it rather than retyping, so a stray
character difference does not leave the `msgstr` orphaned.)

- [ ] **Step 3: Recompile**

Run: `make messages`

(Running it again after editing `.po` files recompiles the `.mo` files from them; it will not
reintroduce empty entries for the ones just filled in.)

- [ ] **Step 4: Verify no empty `msgstr` remains for the new strings**

Run: `grep -A1 "Or a logo address\|Or a landing page logo address\|Fetched and kept as a copy" app/api/locale/cs/LC_MESSAGES/django.po app/api/locale/uk/LC_MESSAGES/django.po`

Expected: every `msgstr` line has non-empty content.

- [ ] **Step 5: Run the translation test**

Run: `uv run pytest tests/test_translations.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api/locale
git commit -m "$(cat <<'EOF'
i18n: translate the branding image address strings

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Document the new behaviour

**Files:**
- Modify: `docs/_architecture/acceptance-criteria.md` (new row)
- Modify: `docs/_architecture/modules/api-ui.md:35` (one clause)

**Interfaces:**
- No code interfaces; this task only adds documentation for behaviour Tasks 1-3 already implement and
  test.

- [ ] **Step 1: Add the acceptance criterion**

At the end of the table in `docs/_architecture/acceptance-criteria.md` (after the existing `AC-127`
row), add:

```markdown
| AC-128 | Branding image address | Logo and hero logo each accept an address instead of a file, at both the global and the quiz level. A valid one is fetched and kept as a local copy; an invalid or unreachable one is refused and nothing else in the save changes. An unchanged address is not re-fetched. | FR-53, FR-14, ADR-0054, ADR-0043 | D |
```

- [ ] **Step 2: Update the "Where things are set" table**

In `docs/_architecture/modules/api-ui.md:35`, the existing branding entry reads (as part of a longer
cell — only this fragment changes):

```text
branding of the application (name, motto, logo, a separate larger logo for the home page, footer, public contact e-mail, and the two colours of `custom` next to the palette; `/admin/settings/branding` for the texts and logos)
```

Change it to:

```text
branding of the application (name, motto, logo, a separate larger logo for the home page, footer, public contact e-mail, and the two colours of `custom` next to the palette; `/admin/settings/branding` for the texts and logos, each logo by upload or by address)
```

- [ ] **Step 3: Check the doc test suite**

Run: `uv run pytest tests/test_docs.py -v`

Expected: PASS (this test checks ID formatting and cross-references, not prose wording, but it is the
cheapest way to catch a malformed table row).

- [ ] **Step 4: Commit**

```bash
git add docs/_architecture/acceptance-criteria.md docs/_architecture/modules/api-ui.md
git commit -m "$(cat <<'EOF'
docs: acceptance criterion for branding images from a URL

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full quality gate**

Run: `make quality`

Expected: lint, the full test suite, gitleaks and the `TECH_DEBT.md` check all pass.

- [ ] **Step 2: Run the integration/wiring checks explicitly**

Run: `make wiring`

Expected: PASS — confirms `fetch_asset_address`/`set_asset` are actually reached from a view, not just
defined.

- [ ] **Step 3: If anything fails, fix forward**

Do not weaken or skip a test to make it pass. If `make quality` surfaces a lint issue (e.g. an unused
import left over from a refactor step), fix it in place and re-run. If a test fails because of a
genuine behaviour gap this plan missed, add the missing test assertion and implementation together,
then re-run from Step 1.

- [ ] **Step 4: Manual check in a real browser (optional but recommended before closing this out)**

This plan's automated tests cover the form/domain logic but not what an admin actually sees. Use the
`kvizotron-browser-walkthrough` skill against a fresh quiz (prefix `url-logo-`) to confirm: the "Or a
logo address" and "Or a landing page logo address" fields render under Look and listing on both the
global settings page and a quiz's settings page, submitting a real reachable HTTPS image address
replaces the logo visibly, and a bad address shows a readable error without losing the other typed
fields.

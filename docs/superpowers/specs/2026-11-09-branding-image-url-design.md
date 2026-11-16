# Branding images from a URL — design

Follow-up to [d1-branding-design.md](2026-11-08-d1-branding-design.md). Reuses the fetch mechanism
of [ADR-0043](../../_architecture/adr/0043-external-images.md) (`b4-external-images-design.md`) for
the branding logo and hero logo.

Marks: **[user]** said by the user, **[docs]** already in `docs/_architecture`, **[call]** the
designer's choice, open to correction.

## Why

Branding's logo and hero logo today accept only a direct file upload. An admin who already has a
logo hosted somewhere (the organisation's own site, a shared drive with a public link) has to
download it and re-upload it. Question images already let an admin give an address instead of a
file **[docs]** (ADR-0043); branding should offer the same **[user]**.

## Goals

- `logo` and `hero_logo` each accept an address as an alternative to a file upload, at both the
  global and the quiz level, mirroring today's file-upload override behaviour **[user]**.
- The address is always fetched and kept as a local copy — never shown to participants directly, never
  reloaded from its own server. No per-field "external" mode, unlike questions **[user]**.
- The same security limits as question images: `https://` only, no login in the address, size cap,
  no internal-network fetch unless the existing global switch allows it, one shared time budget per
  save **[user]**, via `app/providers/media_local/provider.py`'s `check_image_address`/`fetch_image`
  **[docs]**.

## Non-goals

- An `external_image_mode`-style choice for branding (always copy) **[user]**.
- Any other branding field (name, motto, footer, colours) gaining a URL input **[call]**: only the
  two image fields have one.
- A background check of branding addresses after save, unlike the hourly check ADR-0043 runs for
  question addresses **[call]**: branding images change rarely and are re-fetched on every edit, so a
  stale copy only lags behind an edit that already happened.

## Anti-goals

- A branding save that fetches an address and stores the copy, then fails and leaves an orphaned,
  referenced-nowhere asset on disk forever **[call]**: cleanup follows the same `_unused`/`delete_image`
  pattern already used when an asset is replaced.
- A refused address silently keeping a stale logo without telling the admin **[call]**.
- Treating an unreachable internal-network admin account's switch flip as a feature to quietly expand
  here **[docs]**: reuses the existing global `allow_internal_image_addresses` switch, does not add a
  second one for branding.

## Behaviour

### Fields

- `BrandingForm` gains `logo_source` and `hero_logo_source`, both `forms.URLField(required=False)`,
  initial value the field's currently stored address (empty if none or if the current image came
  from an upload with no known address).
- Precedence per field, file wins over address: an uploaded file replaces the image and drops any
  stored address; otherwise `remove_logo`/`remove_hero_logo` removes it; otherwise a non-empty address
  is checked and fetched; otherwise nothing changes for that field **[user]** (mirrors ADR-0043's
  "after files, because a file wins" rule, `app/api/admin_quizzes.py:_fetch_addresses`).
- An address identical to what is already stored, with a copy already present, is not re-fetched
  **[docs]** (ADR-0043: "An unchanged address with a copy is not fetched again"). Unlike the question
  editor, branding does not need a hidden `*_kept_source` echo field to know the previous value — the
  current value is already on the row in the database, so the comparison reads it directly **[call]**.
- Clearing the address field to empty, with no file chosen and the remove checkbox unchecked, is a
  no-op: the stored asset and its address stay as they are **[call]**. Only the remove checkbox deletes
  an image.

### Fetching and errors

- One shared time budget per save (both `logo_source` and `hero_logo_source` fetched within the same
  deadline), a local constant in `admin_branding.py` with the same value as
  `admin_quizzes.FETCHES_SECONDS` (25.0 s) rather than an import between the two — `admin_import.py`
  already keeps its own local copy of this budget rather than importing it **[call]**.
- A malformed address (`ImageAddressInvalid`) is always refused and reported on the field, before
  anything is saved **[docs]** (ADR-0043).
- A valid address that cannot be fetched (`ImageRefused`) is always refused and reported on the
  field — there is no "external" mode to fall back to, so this always blocks the save, unlike a
  question under `external` mode **[user]**.
- Both images are resolved (file/remove/address decided, including the fetch) before any
  `branding.set_*`/`branding.remove_*` call runs, so a refused address leaves every field, including
  the other image and the texts, exactly as it was **[docs]** (today's `BrandingForm.save()` docstring:
  "Raises `ImageRefused` before anything else changes" — this design makes that guarantee hold even
  when both images are edited in the same submit).

## Data model

- `BrandingConfiguration.assets_json` values change shape from a plain asset id string to
  `{"asset": "<id>", "source": "<url>" | null}` **[call]**, matching the shape question images already
  use in their own JSON (`app/contracts/question_image.py`). No column or migration is added —
  `assets_json` is already a JSON field.
- Reading stays backward compatible: a value that is still a plain string (existing rows, written
  before this change) is read as `{"asset": value, "source": None}` **[call]**. New writes always use
  the dict form.
- `app/domain/branding.py` changes:
  - `_replace_asset`, `_set_asset`, `has_logo`, `has_hero_logo`, `resolve` read/write the new shape.
  - Two new functions, `set_logo_address(quiz, url, *, admin_id, deadline)` and
    `set_hero_logo_address(quiz, url, *, admin_id, deadline)`, call
    `media().check_image_address(url)` then `media().fetch_image(url, allow_internal=settings.internal_addresses_allowed(), deadline=deadline)`
    (which stores the image and returns its asset id) and then `_replace_asset(..., source=url)`
    **[call]**. `set_logo`/`set_hero_logo` (file upload, raw bytes) keep their existing signature and
    store with `source=None`.
  - `Branding.sources` (quiz/global/default per field) is unaffected: it already tracks which *level*
    a field came from, not whether that level's value is a file or an address.

## Testing

- `tests/domain/test_branding.py`: `set_logo_address`/`set_hero_logo_address` store a fetched asset
  and its address; a value written in the old plain-string shape still resolves and reports
  `has_logo`/`has_hero_logo` correctly; replacing an address-based logo with a new one deletes the old
  asset when unused, same as today's upload replacement.
- `tests/api/test_admin_branding.py`, modelled on the existing `test_a_logo_is_uploaded_and_removed`
  and `test_a_refused_logo_shows_the_message_and_keeps_the_typed_fields`: a global and a quiz-level
  save via `logo_source`/`hero_logo_source` succeeds and stores a copy; an invalid address is refused
  without saving anything else in the same submit; an unreachable address is refused (no "external"
  fallback); saving the same address twice does not re-fetch (monkeypatched `remote.fetch` call count
  stays at one); a file upload wins over a non-empty `logo_source` in the same submit.
- Network calls mocked via `monkeypatch.setattr(remote, "fetch", ...)`, the same pattern as
  `tests/api/test_external_images.py`.

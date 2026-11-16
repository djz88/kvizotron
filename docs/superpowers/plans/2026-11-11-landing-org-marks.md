# Landing Organisation Marks and Logo Rows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A quiz tile on the landing page shows the quiz's own organisation (small logo and name); a set logo in the admin is removed from a compact row with a thumbnail and the file name.

**Architecture:** `branding.quiz_marks(quizzes, locale)` reads the quizzes' own branding rows in one query and returns a `QuizMark(name, logo_url)` only for quizzes that set their own name or logo. The landing view attaches it to each tile; `landing.html` draws one small line above the title. For the admin, the stored asset entry gains an optional `name` (the uploaded file's base name); `Branding` exposes `logo_label` and `hero_logo_label`; the removal button moves into a compact `.logo-row`.

**Tech Stack:** Django, Jinja2, pytest, `theme.css`.

## Global Constraints

- No new setting; derived from existing quiz branding (ADR-0054). Mobile first: one column, no JavaScript, the whole tile stays one link.
- Admin text (organisation name, file name) is escaped by Jinja; never in `<style>` or `<title>`. No inline style or script (CSP).
- Texts: cs and en for admin, also uk for public (`tests/test_translations.py`); `make messages`, fill `msgstr`, revert unrelated `.mo` noise.
- UI says "běh/run", never "kolo". Every behaviour change has a test that failed first.
- Classification VELKÁ. `kvizotron-check-applied` before review; browser check on a throwaway instance (own DB, `runserver` on `localhost:18999`, admin created with `init_admin`), never the shared stack data.

## Decisions (user, 2026-11-11)

1. Landing tile: logo + organisation name (A). Name only from the quiz's own override, not the global one. Not switchable.
2. **B (colour stripe) is out of this plan**: a tile colour needs a per-tile rule in the `style` block with the nonce and a table of the presets' main colours that exists only in CSS. Raised with the user as a follow-up.
3. Logo removal row: small button, small thumbnail, file name of the own logo (upload: file name; address: the address).

## File Structure

- Modify `app/domain/branding.py` — `QuizMark`, `quiz_marks`, `name` in the asset entry, `Branding.logo_label` / `hero_logo_label`.
- Modify `app/api/admin_forms.py:875` — nothing (it already passes `upload.name`); `branding._stage` uses it.
- Modify `app/api/public.py` (`landing`, `_coming_up`) — attach `mark`.
- Modify `app/api/jinja2/public/landing.html`, `app/api/jinja2/admin/_branding_fields.html`, `app/plugins/theme_default/assets/theme.css`.
- Docs: ADR-0054 addendum, `AC-151`, `AC-152`, README range.
- Tests: `tests/domain/test_branding.py`, `tests/api/test_public_pages.py` (landing), `tests/api/test_admin_branding.py`.

## Interfaces

```python
@dataclass(frozen=True)
class QuizMark:
    name: str          # the quiz's own organisation name in the page language, "" if none
    logo_url: str | None   # the quiz's own bar logo, None if none

def quiz_marks(quizzes: Sequence[Quiz], locale: str) -> dict[UUID, QuizMark]:  # only quizzes with a name or a logo; one query

# Branding gains:  logo_label: str | None;  hero_logo_label: str | None   # file name or source address of the chosen logo
# assets_json[field] = {"asset": id, "source": addr | None, "name": file name | None}
```

---

### Task 1: Name of a stored logo and the labels

- [ ] Tests (`tests/domain/test_branding.py`): an upload with name `"../x/Logo škola.png"` stores `name == "Logo škola.png"` (base name, control characters removed, at most 80 characters); `Upload(data, "")` stores `None`; `resolve().logo_label` is the name; for an address it is the address; an older entry without a name gives `None`; the built-in logo gives `None`. RED, then implement: `_stage` returns `(asset, source, name)`; `_asset_entry` reads `name`; `set_images` writes it; `resolve` fills the two labels from the entry that won.
- [ ] Commit `feat(branding): remember the file name of a chosen logo`.

### Task 2: Marks on the landing page

- [ ] Tests (`test_branding.py`): `quiz_marks` returns nothing for a quiz without own name or logo; the quiz's own name (page language, falling back to cs); the own logo URL; a global name is not a mark; **one query** for several quizzes (`django_assert_num_queries(1)`). (`test_public_pages.py`): the tile shows logo `<img … width="20" height="20" alt="">` and name for a quiz with its own, only the title for others, the name escaped, the same for "Coming up".
- [ ] Implement `quiz_marks`, attach `mark` in `landing` and `_coming_up`, draw in `landing.html` before `<strong>`:

```jinja
{% if quiz.mark %}<small class="quiz-org">{% if quiz.mark.logo_url %}<img src="{{ quiz.mark.logo_url }}" alt="" width="20" height="20">{% endif %}{{ quiz.mark.name }}</small>{% endif %}
```

CSS: `.quiz-org { display:flex; align-items:center; gap:.4rem; margin-bottom:.15rem; color:var(--kvz-muted); font-size:.85rem; overflow:hidden; white-space:nowrap; text-overflow:ellipsis }` and `.quiz-org img { flex:none; object-fit:contain }`.
- [ ] Commit `feat(branding): the organisation of a quiz on its landing tile`.

### Task 3: Compact logo row in the admin

- [ ] Tests (`test_admin_branding.py`): with a set global logo uploaded as `firma.png` the row shows `class="logo-row"`, the thumbnail `/media/…`, the text `firma.png` (escaped), and a button with `aria-label` containing the name; an address shows the address; an old entry without a name shows only the thumbnail; no row without own logo; the same at a quiz for its own logo and none for an inherited one.
- [ ] Implement in `_branding_fields.html`: replace the `<p><button…>` with

```jinja
<p class="logo-row"><img src="{{ url }}" alt="" width="24" height="24"><span class="logo-name" title="{{ label }}">{{ label }}</span><button type="submit" form="clear-{{ base }}" class="secondary outline" aria-label="{{ _('Remove the logo') if base == 'logo' else _('Remove the landing page logo') }}{% if label %}: {{ label }}{% endif %}">{{ _("Remove") }}</button></p>
```

(`url` and `label` from `logo_preview.logo_url` / `.logo_label` or `.hero_logo_url` / `.hero_logo_label`.) CSS: `.logo-row { display:flex; align-items:center; gap:.5rem; min-width:0 }`, `.logo-row img { flex:none; object-fit:contain }`, `.logo-name { flex:1; min-width:0; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; color:var(--kvz-muted); font-size:.9rem }`, `.logo-row button { width:auto; margin:0; padding:.2rem .6rem; font-size:.85rem }`.
- [ ] `make messages`, translations of "Remove". Commit `feat(branding): compact logo row with thumbnail and file name`.

### Task 4: Docs, quality, browser

- [ ] ADR-0054 addendum; `AC-151` (landing tile mark: own name and logo only, escaped, one query, unchanged tile without them), `AC-152` (logo row: thumbnail and file name, aria-label); README range to `AC-152`; name them in test docstrings.
- [ ] `make quality`; browser on a throwaway instance (390 px dark, 1280 px light): a quiz with own name+logo, a long name (ellipsis, tile height stays), a quiz without; admin row for an upload, an address and an old entry.
- [ ] Commit `docs(branding): ADR-0054 addendum, AC-151 and AC-152`.

## Self-Review

Decisions 1 and 3 map to Tasks 2 and 3 (label data in Task 1). Decision 2 (no B) is recorded and must be reported to the user.

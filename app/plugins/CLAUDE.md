# Module: app/plugins

Features that can be enabled and disabled: `questions/` (question types), `scoring/` (scoring), `quiz_flow/` (navigation modes), `quiz_types/` (quiz types: named sets of quiz settings, definitions only, ADR-0062), `theme_default/` (theme), `participants/` (participant rules, ADR-0049), `results/` (official attempt, scoreboard order and summaries, ADR-0051), `rewards/` (reached reward thresholds and three reward settings, ADR-0053), `drawings/` (order, fingerprint and selection of a drawing, ADR-0013 and ADR-0053). Infrastructure is in `app/providers/`.

## What a module contains

`manifest.py` with the mandatory `settings` field (ADR-0042), an entry in `[project.entry-points."kvizotron.modules"]`, `apps.py`, its own templates in `jinja2/<name>/` and a catalog in `locale/`. A new catalog belongs in `ROOTS` in `tools/messages.py`.

## Forbidden

- Importing from `app/domain`, `app/api`, `app/providers` or from another plugin: only `app.contracts` is allowed.
- An answer key in `public_payload()` or in `render_public`.
- Assembling HTML by hand: the output is marked as safe, so only a template with autoescape renders it.
- Own tables without a migration in the module; modifying the domain's tables.

## Watch out

- Every question type has `tests/contracts/test_<type>.py` that inherits `QuestionTypeContract`, and with it the escaping and `describe_definition` tests.
- `describe_definition` must change its output when any field of the definition changes, otherwise the change overview will not show it.
- Inputs are named `<question id>:<field>`. Values arrive as strings; a field ending in `[]` arrives as a list under the name without the brackets.
- The type computes the grade in `grade`, the strategy only weights it. The plugin does not read settings: what it needs, it receives in `quiz_settings`.
- Images are in the definition as `asset`, possibly `source`; what is shown is decided by the API, which fills it into the `url` key.
- The shared question image is in `app/contracts/question_image.py` and the macro in `admin/_image_fields.html`, because plugins must not import one another.
- A type with files returns `file_fields`; the value of such a field is filled in only by the API from a file actually received. `summarize` returns plain text for the public walkthrough and the private link, never markup.
- `from_csv` builds the editor form and calls `parse_admin`, so the file is rejected exactly as the editor would. A cell with an image is only passed on in `source`; the domain distinguishes an address from a file.
- `theme_default/`: the palette from two colours is derived by `colours.py` and every pair must reach 4.5:1 in both light and dark mode (`tests/test_palettes.py`). A new preset needs a token block in `assets/theme.css`, an entry in `PALETTE_CHOICES` and a record in the domain catalog in the same commit. Branding storage is in the domain, the theme cannot reach it (ADR-0054). The footer badges (`assets/badge-*.svg`) are our own text SVGs, not borrowed logos; they are served by `views.asset` according to `TYPES`, so a new file must get a type there.
- Some plugin validation messages are still in English.

## Public API

No imports from outside; other code knows the module only through the registry and the protocol.

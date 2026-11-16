# D1 Branding — design

Milestone D1 of [roadmap.md](../../_architecture/roadmap.md). Finishes `FR-05` and `FR-14`
([plugins/theme-default.md](../../_architecture/plugins/theme-default.md)).

Marks: **[user]** said by the user, **[docs]** already in `docs/_architecture`, **[call]** the
designer's choice, open to correction.

## Why

Quizzes are often run by someone other than the installation's owner: a school class, a club, a
sponsor. Each wants its own name, logo and colours on the pages participants see. The installation
itself also needs one default identity (an "organisation") that every quiz takes until it overrides
it **[user]**. Today the name "Kvízotron", the motto, the logo and the five palettes are fixed in
templates and in the domain catalogue, so neither is possible.

## Goals

- One global identity: name, motto, logo, colours, footer text **[user]**.
- A quiz can override each of the five on its own **[user]**.
- Custom colours from two picked colours, adjusted to WCAG AA, with a notice when adjusted **[user]**.
- Name, motto and footer per language cs/en/uk **[user]**.
- The palette list and the branding capabilities move from the domain catalogue into the theme, behind
  the `ThemePlugin` contract **[docs]** (roadmap D1, FR-14 "only capabilities offered by the current theme").
- A small "runs on Kvízotron" line that always stays **[user]**.

## Non-goals

- Editable menu labels and information pages (How it works, About, Privacy) — dropped from D1
  **[user]**. Roadmap row is updated to say so.
- A second theme. The contract allows one; v1.0 ships only `theme.default` **[docs]**.
- Branding per run or per question **[call]**: the user asked for global + quiz; a run belongs to its quiz.
- Branding on admin pages beyond the global one **[call]**.
- Custom fonts, CSS upload, custom favicon **[call]**.

## Anti-goals

- A page whose text fails WCAG AA because of a custom colour. The server never serves unadjusted
  colours that fail **[user]**.
- A branding change that creates a draft or a new revision **[docs]** (FR-50, ADR-0038).
- Removing every mention of Kvízotron from public pages **[user]**.
- Any HTML or CSS from an admin reaching a page unescaped **[call]**.

## Behaviour

### Where branding applies

- A quiz's public pages use the quiz's resolved branding: quiz page, play, result, private result
  link, walkthrough, scoreboard and projector view, unavailable page of that quiz **[call]**, same rule as
  palettes in FR-53 **[docs]**.
- The landing page, information pages and administration use the global branding **[docs]** (FR-53).
- Preview and test links show the quiz's branding exactly as a run would **[call]**.
- Each field resolves on its own: quiz value, else global value, else built-in default **[user]**
  (ADR-0042 chain without the question level).

### Fields

| Field | Built-in default | Per language | Notes |
|---|---|---|---|
| Name | "Kvízotron" | yes | bar, `<title>`, landing heading |
| Motto | translated "Turn on your brain. Start Kvízotron." | yes | landing hero; quiz page under the name **[call]** |
| Logo | `/assets/logo.svg` | no | bar and landing hero |
| Colours | palette `blue_teal` | no | a preset or "custom" |
| Footer | empty | yes | short plain text, max 300 characters **[call]**, links not rendered as HTML |

- A text field per language: an empty en/uk value falls back to the cs value; all three empty fall
  back to the next level (global, then built-in) **[user]**. A quiz override of a text field counts as
  set when any language is filled **[call]**.
- Footer line on every public page: the footer text (if any), then always a small line
  "Runs on Kvízotron" linking to About **[user]**. It cannot be turned off **[user]**.
- Favicon stays Kvízotron's **[call]**.

### Colours

- `color_palette` keeps its key, scopes (global, quiz) and stored values; the five presets are
  unchanged **[docs]**. Its choices now come from the theme, plus a new choice `custom` **[call]**.
- Choosing `custom` shows two colour inputs: main and accent (`#rrggbb`) **[user]**.
- The palette and its custom colours resolve as one unit: the custom colours come from the same level
  that chose `custom`. A quiz that overrides with `custom` stores its own two colours; a quiz that
  inherits a global `custom` uses the global colours **[call]**. Saving `custom` without both colours is
  refused **[call]**.
- The server derives every token of the theme (bar, page gradient, link, tile, line, surface, on-*
  colours) for light and dark mode from the two colours **[user]**, then adjusts lightness until each
  pair the palette test checks reaches WCAG AA **[user]**. The derivation lives in the theme plugin
  **[call]**.
- When an adjustment changed a picked colour, saving succeeds and the settings page shows a notice:
  the chosen colours do not reach WCAG AA, with the colours actually used shown as swatches **[user]**.
  The notice stays visible while the adjusted values are in use **[call]**.
- Custom colours reach the page as a generated `<style>` block of CSS custom properties built only from
  validated hex values, or a per-scope stylesheet URL — left to the builder; either way no admin text
  reaches CSS **[call]**.
- Without JavaScript the inputs are plain text fields accepting `#rrggbb` **[call]**.

### Logo

- Upload through `MediaStorageProvider.store_image` with its existing checks (PNG, JPEG, WebP, GIF,
  checked SVG) **[call]**. Removing the logo returns to the next level.
- A replaced or removed logo's asset is deleted unless another branding row still refers to it
  **[call]**.
- The logo always has an alt text equal to the resolved name, or empty when shown next to the name
  **[call]**.

### Admin

- Global: `Nastavení`, group `look`: name, motto, footer (cs/en/uk), logo, colours **[call]**.
  Name, logo and colours are `basic`; motto and footer `advanced` (ADR-0052) **[call]**.
- Quiz: the quiz's settings in group `look`, each field with "inherited from global" / override and a
  way to delete the override, same pattern as existing quiz overrides **[call]**.
- Changes take effect immediately and are audited **[docs]** (FR-50).
- Duplicating a quiz does not copy its branding, like its other setting overrides **[call]**. Archiving keeps it.

### Theme contract

`ThemePlugin` gains (names left to the builder) **[call]**:

- the list of palettes with their labels,
- which branding fields the theme supports (name, motto, logo, colours, footer, custom colours),
- deriving the token set from custom colours, with a flag that adjustment happened.

Admin forms show only fields the active theme supports **[docs]** (FR-14). `color_palette` moves from
`app/domain/settings.py` into the `theme.default` manifest's `settings` **[docs]** (roadmap: "the theme takes
over the palette list"). Branding fields other than colours are not catalogue settings, because they are
free text and files, not choices; they live in the table `branding_configuration` (data-model.md) **[docs]**, owned by the domain like the rewards
and results tables, because plugins import only `app.contracts` **[call]**; same inheritance **[call]**. This split is recorded in a new ADR **[call]**.

## Constraints

- Plugins import only `app.contracts` **[docs]**.
- Public texts in cs, en, uk; admin texts in cs and en **[docs]**.
- Every pair of the resulting palette reaches WCAG AA in light and dark; `tests/test_palettes.py`
  keeps checking the presets and a new test checks derived palettes over many random inputs **[call]**.
- No admin input is rendered as HTML or reaches CSS other than as a validated hex colour **[call]**.
- A migration creates `branding_configuration` and keeps existing `color_palette` values **[docs]**.
- Page rendering stays one cheap lookup for branding per request (cached per scope or read with the
  quiz) for ~50 participants **[call]**.

## Risks

- Lightness adjustment may move a brand colour far from what the admin picked; the notice and swatches
  make that visible **[user]**.
- Moving `color_palette` into a module changes where the catalogue entry is declared; a key owned twice
  stops start-up (ADR-0042), so the domain entry must go in the same change **[docs]**.
- One asset referred to by two rows (global and a quiz) **[call]**: covered by the reference check.

## Left to the builder

- Colour derivation algorithm (e.g. HSL/OKLCH lightness steps) as long as AA holds and it is
  deterministic.
- How custom tokens reach the page (inline `<style>` vs stylesheet URL).
- Contract method names and the shape of `tokens_json` / `assets_json`.
- Exact form layout and swatch rendering.

## Verification

- Contract test for the extended `ThemePlugin` in `tests/contracts/`.
- Unit tests: resolution per field across built-in → global → quiz, language fallback, override
  deletion; colour derivation reaches AA for random inputs, adjustment flag set exactly when a colour
  moved; logo asset deleted only when unreferenced.
- Page tests: quiz pages show the quiz's name, logo, colours, footer and the Kvízotron line; the landing,
  info and admin pages show the global ones; preview and test link match; no HTML from fields rendered.
- New AC from AC-94: global identity, quiz override, custom colours with notice, Kvízotron line.
- `make messages` with cs and uk filled.
- Browser walkthrough on `kvizotron-browser` with a new quiz `d1-…`: set global identity, override on
  the quiz, pick colours that fail AA and see the notice, check cs/en/uk, mobile and dark mode.
- `make quality`, `make smoke`.

## Addendum 2026-11-09: footer line, settings navigation, Basic/All switch

Asked by the user after the first review of D1; built on the same branch **[user]**.

### Footer on one line

- Every public page ends with one line, parts separated by " · ", missing parts left out **[user]**:
  footer text (branding) · `GPL-3.0-or-later` linking to About · small badges Python, Django, HTMX ·
  "Runs on Kvízotron <version>" linking to About · current year · contact e-mail as a `mailto:` link **[user]**.
- The version is the installed package version (`importlib.metadata`), today `0.1.0` **[call]**. The year is the
  current year in the configured time zone **[call]**.
- Badges are local SVG files served by the theme, with text alternatives; no request leaves the server **[call]**.
- The line wraps on narrow screens; it is still one paragraph **[call]**. The Kvízotron part still cannot be turned off **[user]**.

### Contact e-mail

- New branding field `contact_email`: global with a quiz override, like the name **[user]**. Validated e-mail,
  max 254 characters **[call]**. It is shown publicly; the form says so **[call]**.
- Fallback when neither level sets it: the e-mail of the admin account that created the quiz **[user]**. Pages
  without a quiz have no fallback **[call]**.
- Admin accounts gain an optional e-mail, set on `Správci` **[user, as a consequence]**; its help says it can appear
  in quiz footers **[call]**. Participant e-mails are never shown; this concerns admins only **[docs]**.
- A quiz remembers who created it (new quiz, duplicate) **[user]**. Existing quizzes get it retroactively **[user]**:
  the admin of the oldest audit event that names the quiz, else the oldest admin account **[call]**.

### Floating section navigation and the Basic/All switch

- Global settings, quiz settings and the run plan get a floating panel with links to their sections **[user]**:
  on wide screens a panel at the side that stays while scrolling and marks the current section; on a phone a
  floating "Sections" button that opens the list **[user]**. Works without JavaScript (anchor links, `<details>`)
  **[call]**; highlighting the current section is JavaScript only **[call]**.
- The Basic/All switch moves into that panel on each of those pages and leaves the top bar **[user]**. The choice
  is still remembered for all pages **[call]**.

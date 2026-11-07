# Plugin: default theme

| | |
|---|---|
| Contract | `ThemePlugin` |
| Package | `app/plugins/theme_default/` |
| Stage | A (base), D (branding contract) |

## Requirements

- `FR-05` UI is responsive, mobile-first, keyboard accessible; modern default theme with subtle
  animations and a progress indicator. v1.0 ships a single theme, but the `ThemePlugin` contract
  allows adding more.
- `FR-14` Default application name and identity: **Kvízotron**, slogan **„Zapni mozek. Spusť
  Kvízotron.“**. Branding settings are global (name, slogan, logo, colours, header/footer) with
  per-quiz override. Admin can configure only capabilities offered by the current theme.

## Current state (A4)

Layout on vendored Pico CSS, responsive, with a skip link and keyboard-reachable controls. A theme
template with the name of a page template replaces that page, because themes load before `app.api`.
Colours are token blocks per palette in `assets/theme.css`, selected by `data-palette` on `<html>`, and `tests/test_palettes.py` reads them to check contrast. The progress indicator of FR-05 came with navigation modes in B3; the rest of FR-05 is finished in D1.

## Data owned

`branding_configuration` (scope, scope_id, theme_id, tokens_json, assets_json).

## Extension points (LATER)

Further themes as additional `ThemePlugin` plugins.

# Plugin: default theme

| | |
|---|---|
| Contract | `ThemePlugin` |
| Package | `app/plugins/theme_default/` |
| Stage | A (base), D1 (branding contract) |

## Requirements

- `FR-05` UI is responsive, mobile-first, keyboard accessible; modern default theme with subtle
  animations and a progress indicator. v1.0 ships a single theme, but the `ThemePlugin` contract
  allows adding more.
- `FR-14` Default application name and identity: **Kvízotron**, slogan **„Zapni mozek. Spusť
  Kvízotron.“**. Branding settings are global (name, slogan, logo, colours, footer, contact e-mail) with
  per-quiz override. Admin can configure only capabilities offered by the current theme.

## Current state (A4)

Layout on vendored Pico CSS, responsive, with a skip link and keyboard-reachable controls. A theme
template with the name of a page template replaces that page, because themes load before `app.api`.
Colours are token blocks per palette in `assets/theme.css`, selected by `data-palette` on `<html>`, and `tests/test_palettes.py` reads them to check contrast. The progress indicator of FR-05 came with navigation modes in B3; the rest of FR-05 was finished in D1.

## Branding (D1)

The theme declares its preset palettes, the branding fields it supports and a derivation of a full palette from a main and an accent colour (`ThemePlugin`, [plugin-api.md](../../plugin-api.md)). The derivation lives in `app/plugins/theme_default/colours.py`: every text colour is built to reach 4.5:1, a main or accent colour that is itself a background or text is darkened in steps of 2 % lightness until it does, and the result says it was adjusted. The layout shows name, logo and footer, serves the three footer badges (`assets/badge-*.svg`, text SVGs made for the project) from its asset view, and renders the custom palette as a `<style>` block with a nonce only when the page uses it. Storage and resolution are the domain's, see [ADR-0054](../adr/0054-branding-owned-by-domain-and-theme.md).

## Data owned

None; `branding_configuration` belongs to the domain.

## Extension points (LATER)

Further themes as additional `ThemePlugin` plugins.

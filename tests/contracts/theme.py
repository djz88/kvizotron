"""Shared contract suite: every theme must pass it (contracts.md)."""

import re

from django.template.loader import get_template

from app.contracts import (
    BRANDING_FIELDS,
    CUSTOM_PALETTE,
    PALETTE_TOKENS,
    BrandColours,
    DerivedPalette,
    ThemePlugin,
)

HEX = re.compile(r"#[0-9a-f]{6}")


class ThemeContract:
    plugin: ThemePlugin

    def test_satisfies_protocol(self):
        assert isinstance(self.plugin, ThemePlugin)

    def test_layout_template_loads(self):
        assert get_template(self.plugin.layout_template())

    def test_palettes_are_presets_without_custom(self):
        palettes = list(self.plugin.palettes())
        assert palettes
        assert CUSTOM_PALETTE not in palettes
        assert len(set(palettes)) == len(palettes)

    def test_branding_fields_are_known(self):
        assert self.plugin.branding_fields() <= frozenset(BRANDING_FIELDS)

    def test_derived_palette_has_every_token_as_hex_in_both_modes(self):
        derived = self.plugin.derive_palette(BrandColours("#1769E0", "#ffb020"))
        assert isinstance(derived, DerivedPalette)
        for mode in (derived.light, derived.dark):
            assert set(mode) == set(PALETTE_TOKENS)
            assert all(HEX.fullmatch(value) for value in mode.values())
        assert HEX.fullmatch(derived.main) and HEX.fullmatch(derived.accent)

    def test_derivation_is_deterministic(self):
        colours = BrandColours("#ffff00", "#123456")
        assert self.plugin.derive_palette(colours) == self.plugin.derive_palette(colours)

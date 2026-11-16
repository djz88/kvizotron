"""Custom colours are turned into a palette whose text stays readable (WCAG AA)."""

import random

import pytest

from app.contracts import BrandColours
from app.plugins.theme_default.plugin import DefaultTheme
from tests.test_palettes import PAIRS, contrast


def random_hex(rng: random.Random) -> str:
    return f"#{rng.randrange(0x1000000):06x}"


SEEDED = random.Random(20261108)  # noqa: S311  # repeatable test data, not secrets
CASES = [(random_hex(SEEDED), random_hex(SEEDED)) for _ in range(200)] + [
    ("#ffff00", "#ffff00"),
    ("#000000", "#ffffff"),
    ("#1769e0", "#ffb020"),
]


@pytest.mark.parametrize(("main", "accent"), CASES)
def test_every_pair_reaches_aa_in_both_modes(main, accent):
    derived = DefaultTheme().derive_palette(BrandColours(main, accent))
    for mode in (derived.light, derived.dark):
        for foreground, background in PAIRS:
            ratio = contrast(mode[foreground], mode[background])
            assert ratio >= 4.5, f"{main} {accent}: {foreground} on {background}: {ratio:.2f}"


def test_colours_that_already_pass_are_used_as_given():
    derived = DefaultTheme().derive_palette(BrandColours("#1769E0", "#FFB020"))
    assert derived.adjusted is False
    assert (derived.main, derived.accent) == ("#1769e0", "#ffb020")
    assert derived.light["main"] == "#1769e0" and derived.light["accent"] == "#ffb020"


def test_a_very_light_main_colour_is_adjusted():
    derived = DefaultTheme().derive_palette(BrandColours("#ffff00", "#ffff00"))
    assert derived.adjusted is True
    assert derived.main != "#ffff00"
    assert derived.light["main"] == derived.main


@pytest.mark.parametrize("colour", ["red", "#fff", "#gggggg", "1769e0", "#1769e0 "])
def test_only_rrggbb_is_accepted(colour):
    with pytest.raises(ValueError):
        DefaultTheme().derive_palette(BrandColours(colour, "#ffffff"))

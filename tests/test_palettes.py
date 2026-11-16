"""Every palette is readable in light and dark mode (FR-53). WCAG AA: 4.5 for normal text."""

import re
from pathlib import Path

import pytest

from app.contracts import COLOR_PALETTE, CUSTOM_PALETTE
from app.domain import settings
from app.plugins.theme_default.manifest import PALETTE_CHOICES

CSS = (
    Path(__file__).resolve().parents[1] / "app/plugins/theme_default/assets/theme.css"
).read_text(encoding="utf-8")
PALETTES = [choice for choice in PALETTE_CHOICES if choice != CUSTOM_PALETTE]
MODES = ["light", "dark"]


def block(name: str) -> dict[str, str]:
    """Blocks are marked `/* palette: name */ ... /* end */` so a test can read them."""
    found = re.search(rf"/\* palette: {name} \*/(.*?)/\* end \*/", CSS, re.S)
    assert found, name
    return dict(re.findall(r"--kvz-([a-z-]+):\s*(#[0-9a-f]{6})", found.group(1)))


def tokens(palette: str, mode: str) -> dict[str, str]:
    return block(f"{palette} {mode}")


def luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


PAIRS = [
    ("text", "card"),
    ("muted", "card"),
    ("text", "tile"),
    ("on-accent", "accent"),
    ("on-main", "main"),
    ("on-page", "page-from"),
    ("on-page", "page-to"),
    ("on-bar", "bar"),
    ("link", "card"),
]


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("foreground", "background"), PAIRS)
def test_palette_text_reaches_wcag_aa(palette, mode, foreground, background):
    values = tokens(palette, mode)
    ratio = contrast(values[foreground], values[background])
    assert ratio >= 4.5, f"{foreground} on {background}: {ratio:.2f}"


def test_contrast_formula():
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


def test_default_tokens_equal_the_default_palette_so_unknown_values_stay_readable():
    default = settings.CATALOGUE[COLOR_PALETTE].default
    for mode in MODES:
        assert block(f"default {mode}") == tokens(default, mode)


def test_a_stored_value_outside_the_catalogue_has_no_block():
    assert 'data-palette="neon"' not in CSS


def test_violet_palette_is_violet_and_white():
    assert "violet_white" in PALETTES and "violet_orange" not in PALETTES
    for mode in MODES:
        values = tokens("violet_white", mode)
        assert "#ffffff" in (values["accent"], values["on-accent"])


def test_footer_paragraphs_use_the_page_text_colour() -> None:
    """AC-97: Pico colours every `<p>` with `--kvz-text`, which is dark on the page gradient in
    light mode. The footer's paragraphs must set the on-page colour themselves, not inherit it."""
    rules = re.findall(r"([^{}]+)\{([^}]*)\}", CSS)
    footer_text = [body for selector, body in rules if ".site-footer-line" in selector]
    assert footer_text, "no rule for .site-footer-line"
    assert any("color: var(--kvz-on-page)" in body for body in footer_text)

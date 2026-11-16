"""A palette from two colours, built the way the presets in `theme.css` are.

Every text colour is derived so it reaches WCAG AA (4.5:1) on its background. Where the main or
accent colour itself is the background or the text, that colour is darkened in steps of 2 % HSL
lightness until it does, and the palette says it was adjusted (ADR-0054).
"""

import colorsys
import re

from app.contracts import BrandColours, DerivedPalette

AA = 4.5
STEP = 0.02
HEX = re.compile(r"#[0-9a-fA-F]{6}")
BLACK = "#000000"
WHITE = "#ffffff"
# Foreground, background: the pairs that carry text.
PAIRS = (
    ("text", "card"),
    ("muted", "card"),
    ("text", "tile"),
    ("on-accent", "accent"),
    ("on-main", "main"),
    ("on-page", "page-from"),
    ("on-page", "page-to"),
    ("on-bar", "bar"),
    ("link", "card"),
)
PAGE_HUE_SHIFT = -35 / 360  # blue_teal: #1769e0 to #0e7c7c


def checked(colour: str) -> str:
    if not HEX.fullmatch(colour):
        raise ValueError(f"Not a #rrggbb colour: {colour!r}")
    return colour.lower()


def luminance(colour: str) -> float:
    channels = [int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def to_hls(colour: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)))


def from_hls(hue: float, lightness: float, saturation: float) -> str:
    lightness = min(1.0, max(0.0, lightness))
    red, green, blue = colorsys.hls_to_rgb(hue % 1.0, lightness, saturation)
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in (red, green, blue))


def hsl(hue: float, saturation: float, lightness: float) -> str:
    return from_hls(hue, lightness, saturation)


def black_or_white(*backgrounds: str) -> str:
    """Whichever of the two reads better on the worst of the backgrounds."""
    on_black = min(contrast(BLACK, background) for background in backgrounds)
    on_white = min(contrast(WHITE, background) for background in backgrounds)
    return WHITE if on_white >= on_black else BLACK


def readable(colour: str, *backgrounds: str, darker: bool) -> str:
    """`colour`, its lightness stepped away from the backgrounds until each reaches AA."""
    hue, lightness, saturation = to_hls(colour)
    while min(contrast(colour, background) for background in backgrounds) < AA:
        lightness += -STEP if darker else STEP
        colour = from_hls(hue, lightness, saturation)
        if lightness <= 0 or lightness >= 1:
            return colour
    return colour


def tokens(main: str, accent: str) -> tuple[dict[str, str], dict[str, str]]:
    hue, _, saturation = to_hls(main)
    bar = hsl(hue, min(saturation, 0.7), 0.19)
    on_main = black_or_white(main)
    page_to = hsl(hue + PAGE_HUE_SHIFT, saturation, to_hls(main)[1])
    page_to = readable(page_to, on_main, darker=on_main == WHITE)
    tile = hsl(hue, 0.6, 0.96)
    light = {
        "main": main,
        "on-main": on_main,
        "page-from": main,
        "page-to": page_to,
        "on-page": on_main,
        "bar": bar,
        "on-bar": black_or_white(bar),
        "accent": accent,
        "on-accent": black_or_white(accent),
        "card": WHITE,
        "text": readable(bar, WHITE, tile, darker=True),
        "muted": readable(hsl(hue, 0.12, 0.40), WHITE, darker=True),
        "tile": tile,
        "link": main,
        "line": hsl(hue, 0.3, 0.88),
        "surface": hsl(hue, 0.4, 0.97),
    }
    card = hsl(hue, 0.45, 0.16)
    dark_tile = hsl(hue, 0.35, 0.23)
    dark = {
        "main": main,
        "on-main": on_main,
        "page-from": bar,
        "page-to": main,
        "on-page": black_or_white(bar, main),
        "bar": bar,
        "on-bar": black_or_white(bar),
        "accent": accent,
        "on-accent": black_or_white(accent),
        "card": card,
        "text": readable(hsl(hue, 0.5, 0.95), card, dark_tile, darker=False),
        "muted": readable(hsl(hue, 0.2, 0.78), card, darker=False),
        "tile": dark_tile,
        "link": readable(hsl(hue, 0.9, 0.78), card, darker=False),
        "line": hsl(hue, 0.3, 0.30),
        "surface": hsl(hue, 0.5, 0.12),
    }
    return light, dark


def failing(*modes: dict[str, str]) -> set[str]:
    """Tokens in a pair below AA."""
    return {
        token
        for mode in modes
        for foreground, background in PAIRS
        if contrast(mode[foreground], mode[background]) < AA
        for token in (foreground, background)
    }


def darker(colour: str) -> str:
    hue, lightness, saturation = to_hls(colour)
    return from_hls(hue, max(0.0, lightness - STEP), saturation)


def derive_palette(colours: BrandColours) -> DerivedPalette:
    given_main, given_accent = checked(colours.main), checked(colours.accent)
    main, accent = given_main, given_accent
    while True:
        light, dark = tokens(main, accent)
        offending = failing(light, dark)
        if not offending:
            break
        if offending & {"accent", "on-accent"} and accent != BLACK:
            accent = darker(accent)
        elif main != BLACK:
            main = darker(main)
        else:  # black reaches AA with white everywhere; kept so the loop always ends
            break
    return DerivedPalette(
        light=light,
        dark=dark,
        adjusted=(main, accent) != (given_main, given_accent),
        main=main,
        accent=accent,
    )

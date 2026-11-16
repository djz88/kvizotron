import hashlib
from collections.abc import Sequence
from functools import cache
from pathlib import Path

from django.urls import reverse

from app.contracts import (
    BRANDING_FIELDS,
    CUSTOM_PALETTE,
    BrandColours,
    DerivedPalette,
)
from app.plugins.theme_default.colours import derive_palette
from app.plugins.theme_default.manifest import PALETTE_CHOICES

ASSETS = Path(__file__).parent / "assets"


@cache
def _digest(path: Path, modified: int, size: int) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def versioned(address: str, path: Path) -> str:
    """`address?v=<fingerprint>`: files are served with `max-age`, so without the content in the
    address a browser keeps an old copy that long after a deploy. Read again when the file changes.
    """
    found = path.stat()
    return f"{address}?v={_digest(path, found.st_mtime_ns, found.st_size)}"


class DefaultTheme:
    id = "default"
    version = "1.0.0"

    def layout_template(self) -> str:
        return "theme_default/layout.html"

    def stylesheet_urls(self) -> Sequence[str]:
        return [
            versioned(reverse("theme.default:asset", args=[name]), ASSETS / name)
            for name in ("pico.min.css", "theme.css")
        ]

    def palettes(self) -> Sequence[str]:
        """The presets with a block in theme.css, in the order the manifest offers them."""
        return [choice for choice in PALETTE_CHOICES if choice != CUSTOM_PALETTE]

    def branding_fields(self) -> frozenset[str]:
        return frozenset(BRANDING_FIELDS)

    def derive_palette(self, colours: BrandColours) -> DerivedPalette:
        return derive_palette(colours)

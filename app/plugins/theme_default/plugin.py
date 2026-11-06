from collections.abc import Sequence

from django.urls import reverse


class DefaultTheme:
    id = "default"
    version = "1.0.0"

    def layout_template(self) -> str:
        return "theme_default/layout.html"

    def stylesheet_urls(self) -> Sequence[str]:
        return [reverse("theme.default:asset", args=[n]) for n in ("pico.min.css", "theme.css")]

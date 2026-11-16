def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


# Each preset has a token block in assets/theme.css (FR-53); "custom" is derived from the branding's
# two colours (ADR-0054).
PALETTE_CHOICES = ["blue_teal", "indigo_pink", "violet_white", "green_blue", "red_plum", "custom"]

MANIFEST = {
    "id": "theme.default",
    "name": _("Default theme"),
    "description": _("The look of the pages and the colour palettes."),
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.theme_default.apps.ThemeDefaultConfig",
    "urls": "app.plugins.theme_default.urls",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["theme"],
    "settings": [
        {
            "key": "color_palette",
            "group": "look",
            "level": "basic",
            "choices": PALETTE_CHOICES,
            "default": "blue_teal",
            "scopes": ["global", "quiz"],
            "scope_reason": "Colours belong to the quiz's pages, and a page holds many questions.",
            "label": _("Colours"),
            "value_labels": {
                "blue_teal": _("Blue and teal"),
                "indigo_pink": _("Indigo and pink"),
                "violet_white": _("Violet and white"),
                "green_blue": _("Green and blue"),
                "red_plum": _("Red and plum"),
                "custom": _("Custom colours"),
            },
        }
    ],
}

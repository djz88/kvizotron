def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "drawings.manual",
    "name": _("Draw"),
    "description": _("Draws reward winners and keeps the history of draws."),
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.drawings.apps.DrawingsConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["drawing"],
    "requires": [],
    "activation_scope": ["global"],
    "settings": [],
}

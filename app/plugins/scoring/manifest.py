def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "scoring.basic",
    "name": _("Scoring"),
    "description": _("Counts points for an answer."),
    "always_on": True,
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.scoring.apps.ScoringBasicConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["scoring_strategy"],
    "settings": [],
}

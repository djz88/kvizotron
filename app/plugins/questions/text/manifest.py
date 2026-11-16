def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "question.text",
    "name": _("Text answer"),
    "description": _("Questions answered by typing a text."),
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.questions.text.apps.TextConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["question_type"],
    "requires": ["scoring_strategy"],
    "activation_scope": ["global", "quiz"],
    "settings": [],
}

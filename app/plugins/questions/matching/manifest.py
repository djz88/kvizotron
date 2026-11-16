def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "question.matching",
    "name": _("Matching"),
    "description": _("Questions that pair items or put them in order."),
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.questions.matching.apps.MatchingConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["question_type"],
    "requires": ["scoring_strategy"],
    "activation_scope": ["global", "quiz"],
    "settings": [],
}

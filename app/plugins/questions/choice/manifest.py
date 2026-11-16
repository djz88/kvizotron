def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "question.choice",
    "name": _("Choice"),
    "description": _("Questions with one, several or no correct answers."),
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.questions.choice.apps.ChoiceConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["question_type"],
    "requires": ["scoring_strategy"],
    "activation_scope": ["global", "quiz"],
    "settings": [],
}

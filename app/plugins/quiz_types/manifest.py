def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "quiz_types.basic",
    "name": _("Quiz types"),
    "description": _("Named bundles of quiz settings, such as a practice quiz or a contest."),
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.quiz_types.apps.QuizTypesConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["quiz_type"],
    "requires": [],
    "activation_scope": ["global"],
    "settings": [],
}

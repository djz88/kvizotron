MANIFEST = {
    "id": "question.number",
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.questions.number.apps.NumberConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["question_type"],
    "requires": ["scoring_strategy"],
    "activation_scope": ["global", "quiz"],
    "settings": [],
}

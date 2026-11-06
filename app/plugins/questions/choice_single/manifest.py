MANIFEST = {
    "id": "question.choice_single",
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.questions.choice_single.apps.ChoiceSingleConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["question_type"],
    "requires": ["scoring_strategy"],
    "activation_scope": ["global", "quiz"],
}

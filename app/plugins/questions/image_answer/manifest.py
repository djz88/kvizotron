def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "question.image_answer",
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.questions.image_answer.apps.ImageAnswerConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["question_type"],
    "requires": ["scoring_strategy", "media_storage"],
    "activation_scope": ["global", "quiz"],
    "settings": [
        {
            "key": "photo_visibility",
            "group": "answers",
            "choices": ["author", "admins", "public"],
            "default": "author",
            "label": _("Who sees a photo"),
            "value_labels": {
                "author": _("Admins and its author"),
                "admins": _("Admins"),
                "public": _("Its author, and everyone once an admin approves that photo"),
            },
            "help": _(
                "With the last value, participants are told before uploading that a photo may be "
                "shown publicly after the run ends."
            ),
        }
    ],
    "settings_requirements": {
        "reveal_moment": {
            "refuse": ["after_each"],
            "use": "at_end",
            "reason": _(
                "A photo question needs a person to grade it, so answers cannot be shown "
                "after each question."
            ),
        }
    },
}

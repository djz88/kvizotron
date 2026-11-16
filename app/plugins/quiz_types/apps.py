from django.apps import AppConfig


class QuizTypesConfig(AppConfig):
    name = "app.plugins.quiz_types"
    label = "quiz_types"

    def ready(self):
        from app.kernel import registry

        from .plugin import TYPES

        for quiz_type in TYPES:
            registry.register("quiz_type", quiz_type.id, quiz_type, "quiz_types.basic")

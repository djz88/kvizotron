from django.apps import AppConfig


class MatchingConfig(AppConfig):
    name = "app.plugins.questions.matching"
    label = "question_matching"

    def ready(self):
        from app.kernel import registry

        from .plugin import MatchingQuestion

        plugin = MatchingQuestion()
        registry.register("question_type", plugin.id, plugin, "question.matching")

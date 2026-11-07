from django.apps import AppConfig


class ChoiceConfig(AppConfig):
    name = "app.plugins.questions.choice"
    label = "question_choice"

    def ready(self):
        from app.kernel import registry

        from .plugin import ChoiceQuestion

        plugin = ChoiceQuestion()
        registry.register("question_type", plugin.id, plugin, "question.choice")

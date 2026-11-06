from django.apps import AppConfig


class ChoiceSingleConfig(AppConfig):
    name = "app.plugins.questions.choice_single"
    label = "choice_single"

    def ready(self):
        from app.kernel import registry

        from .plugin import ChoiceSingleQuestion

        plugin = ChoiceSingleQuestion()
        registry.register("question_type", plugin.id, plugin, "question.choice_single")

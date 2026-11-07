from django.apps import AppConfig


class NumberConfig(AppConfig):
    name = "app.plugins.questions.number"
    label = "question_number"

    def ready(self):
        from app.kernel import registry

        from .plugin import NumberQuestion

        plugin = NumberQuestion()
        registry.register("question_type", plugin.id, plugin, "question.number")

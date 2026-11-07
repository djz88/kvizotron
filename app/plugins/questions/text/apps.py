from django.apps import AppConfig


class TextConfig(AppConfig):
    name = "app.plugins.questions.text"
    label = "question_text"

    def ready(self):
        from app.kernel import registry

        from .plugin import TextQuestion

        plugin = TextQuestion()
        registry.register("question_type", plugin.id, plugin, "question.text")

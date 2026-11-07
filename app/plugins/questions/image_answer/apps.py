from django.apps import AppConfig


class ImageAnswerConfig(AppConfig):
    name = "app.plugins.questions.image_answer"
    label = "question_image_answer"

    def ready(self):
        from app.kernel import registry

        from .plugin import ImageAnswerQuestion

        plugin = ImageAnswerQuestion()
        registry.register("question_type", plugin.id, plugin, "question.image_answer")

from django.apps import AppConfig


class QuizFlowConfig(AppConfig):
    name = "app.plugins.quiz_flow"
    label = "quiz_flow"

    def ready(self):
        from app.kernel import registry

        from .plugin import BasicFlow

        plugin = BasicFlow()
        registry.register("quiz_flow", plugin.id, plugin, "flow.basic")

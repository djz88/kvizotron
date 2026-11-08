from django.apps import AppConfig


class ResultsConfig(AppConfig):
    name = "app.plugins.results"
    label = "results"

    def ready(self):
        from app.kernel import registry

        from .ranking import LocalResultView

        plugin = LocalResultView()
        registry.register("result_view", plugin.id, plugin, "results.local")

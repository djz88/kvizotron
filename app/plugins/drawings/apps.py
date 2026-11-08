from django.apps import AppConfig


class DrawingsConfig(AppConfig):
    name = "app.plugins.drawings"
    label = "drawings"

    def ready(self):
        from app.kernel import registry

        from .selection import ManualDrawing

        plugin = ManualDrawing()
        registry.register("drawing", plugin.id, plugin, "drawings.manual")

from django.apps import AppConfig


class ThemeDefaultConfig(AppConfig):
    name = "app.plugins.theme_default"
    label = "theme_default"

    def ready(self):
        from app.kernel import registry

        from .plugin import DefaultTheme

        registry.register("theme", DefaultTheme.id, DefaultTheme(), "theme.default")

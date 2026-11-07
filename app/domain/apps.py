from django.apps import AppConfig


class DomainConfig(AppConfig):
    name = "app.domain"
    label = "domain"

    def ready(self):
        from app.domain import settings, usage
        from app.kernel import lifecycle
        from app.kernel.discovery import load_modules

        settings.register_modules(load_modules())

        lifecycle.register_usage_check(usage.question_type_usage)
        lifecycle.register_startup_check(usage.missing_plugin_problems)

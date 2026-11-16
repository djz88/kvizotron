from django.apps import AppConfig


class RetentionConfig(AppConfig):
    name = "app.providers.retention"
    label = "retention"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from app.kernel import registry

        from .provider import LocalRetention

        registry.register("retention", LocalRetention.id, LocalRetention(), "retention.local")

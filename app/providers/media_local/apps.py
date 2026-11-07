from django.apps import AppConfig


class MediaLocalConfig(AppConfig):
    name = "app.providers.media_local"
    label = "media_local"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from app.kernel import registry

        from .provider import LocalMediaStorage

        registry.register("media_storage", LocalMediaStorage.id, LocalMediaStorage(), "media.local")

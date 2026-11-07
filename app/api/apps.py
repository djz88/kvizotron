from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = "app.api"
    label = "api"

    def ready(self):
        from app.api.play import accepts_upload
        from app.api.rendering import last_theme_usage
        from app.kernel import lifecycle, middleware

        middleware.public_upload_check = accepts_upload
        lifecycle.register_usage_check(last_theme_usage)

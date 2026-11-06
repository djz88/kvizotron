from django.conf import settings
from django.urls import include, path

from app.api import play, public
from app.api.health import health

urlpatterns = [
    path("healthz", health),
    path("admin/", include("app.api.admin_urls")),
    path("", public.landing, name="landing"),
    path("q/<slug:slug>", public.quiz, name="quiz"),
    path("q/<slug:slug>/r/<uuid:run_id>", public.quiz_run, name="quiz_run"),
    path("r/<uuid:run_id>/start", play.start, name="start"),
    path("a/<uuid:attempt_id>/submit", play.submit, name="submit"),
    path("assets/<str:name>", public.asset, name="asset"),
    *[
        path(f"m/{module.id}/", include((module.urls, module.id), namespace=module.id))
        for module in settings.KVZ_MODULES
        if module.urls
    ],
]

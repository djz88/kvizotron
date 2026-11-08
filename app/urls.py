from django.conf import settings
from django.urls import include, path

from app.api import play, public, scoreboard
from app.api.health import health

urlpatterns = [
    path("healthz", health),
    path("admin/", include("app.api.admin_urls")),
    path("", public.landing, name="landing"),
    path("how-it-works", public.info_page, {"template": "how_it_works"}, name="how_it_works"),
    path("about", public.info_page, {"template": "about"}, name="about"),
    path("privacy", public.info_page, {"template": "privacy"}, name="privacy"),
    path("q/<slug:slug>", public.quiz, name="quiz"),
    path("q/<slug:slug>/r/<uuid:run_id>", public.quiz_run, name="quiz_run"),
    path("q/<slug:slug>/r/<uuid:run_id>/answers", public.walkthrough_page, name="walkthrough_page"),
    path("q/<slug:slug>/r/<uuid:run_id>/scoreboard", scoreboard.scoreboard, name="scoreboard"),
    path(
        "q/<slug:slug>/r/<uuid:run_id>/scoreboard/rows",
        scoreboard.scoreboard_rows,
        name="scoreboard_rows",
    ),
    path(
        "q/<slug:slug>/r/<uuid:run_id>/photo/<uuid:answer_id>",
        public.walkthrough_photo,
        name="walkthrough_photo",
    ),
    path("t/<str:token>", public.test_link, name="test_link"),
    path("v/<str:token>", public.result, name="result"),
    path("v/<str:token>/identity", public.result_identity, name="result_identity"),
    path("v/<str:token>/photo/<uuid:answer_id>", public.result_photo, name="result_photo"),
    path("r/<uuid:run_id>/start", play.start, name="start"),
    path("r/<uuid:run_id>/resume", play.resume, name="resume"),
    path("r/<uuid:run_id>/code", play.enter_code, name="run_code"),
    path("a/<uuid:attempt_id>/submit", play.submit, name="submit"),
    path("a/<uuid:attempt_id>/check", play.check, name="check"),
    path("a/<uuid:attempt_id>/time", play.attempt_time, name="attempt_time"),
    path("a/<uuid:attempt_id>/switch", play.switch, name="switch"),
    path("a/<uuid:attempt_id>/revision-status", play.revision_status, name="revision_status"),
    path("assets/<str:name>", public.asset, name="asset"),
    path("media/<uuid:asset_id>", public.media, name="media"),
    *[
        path(f"m/{module.id}/", include((module.urls, module.id), namespace=module.id))
        for module in settings.KVZ_MODULES
        if module.urls
    ],
]

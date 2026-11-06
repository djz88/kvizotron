"""Public pages (FR-01, FR-02, FR-03). They read only the published revision of a run."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.utils.translation import gettext as _

from app.api import i18n
from app.api.rendering import page
from app.domain.models import Quiz, QuizRun

ASSETS = Path(__file__).parent / "assets"
SERVED_ASSETS = frozenset({"htmx.min.js", "play.js"})


def _title(snapshot: Mapping[str, Any], locale: str) -> str:
    return snapshot["title"].get(locale) or snapshot["title"].get(snapshot["default_locale"], "")


def landing(request: HttpRequest) -> HttpResponse:
    locale = request.locale  # type: ignore[attr-defined]
    runs = QuizRun.objects.filter(status=QuizRun.Status.OPEN).select_related(
        "quiz", "current_revision"
    )
    quizzes = [
        {
            "slug": run.quiz.slug,
            "title": _title(run.current_revision.snapshot_json, locale),
            "featured": run.quiz.featured,
        }
        for run in runs.order_by("-quiz__featured", "-opened_at")
    ]
    context = {"quizzes": quizzes, "languages": _languages(i18n.PUBLIC_LOCALES)}
    return page(request, "public/landing.html", context, locale)


def _languages(codes: Any) -> list[dict[str, str]]:
    names = dict(settings.LANGUAGES)
    return [{"code": code, "name": names[code]} for code in codes]


def _unavailable(request: HttpRequest, message: str) -> HttpResponse:
    locale = request.locale  # type: ignore[attr-defined]
    return page(request, "public/unavailable.html", {"message": message}, locale, status=404)


def quiz(request: HttpRequest, slug: str) -> HttpResponse:
    found = Quiz.objects.filter(slug=slug).first()
    if found is None:
        return _unavailable(request, _("This quiz does not exist."))
    run = found.runs.filter(status=QuizRun.Status.OPEN).select_related("current_revision").first()
    if run is None:
        return _unavailable(request, _("This quiz is not running right now."))
    return _quiz_page(request, run)


def quiz_run(request: HttpRequest, slug: str, run_id: UUID) -> HttpResponse:
    run = (
        QuizRun.objects.filter(pk=run_id, quiz__slug=slug)
        .select_related("current_revision")
        .first()
    )
    if run is None:
        return _unavailable(request, _("This quiz does not exist."))
    return _quiz_page(request, run)


def _quiz_page(request: HttpRequest, run: QuizRun) -> HttpResponse:
    snapshot = run.current_revision.snapshot_json
    locale = i18n.negotiate(request, snapshot["locales"], snapshot["default_locale"])
    context = {
        "title": _title(snapshot, locale),
        "run": run,
        "is_open": run.status == QuizRun.Status.OPEN,
        "question_count": len(snapshot["questions"]),
        "languages": _languages(snapshot["locales"]),
    }
    return page(request, "public/quiz.html", context, locale)


def asset(request: HttpRequest, name: str) -> FileResponse:
    if name not in SERVED_ASSETS:
        raise Http404
    response = FileResponse((ASSETS / name).open("rb"), content_type="text/javascript")
    response["Cache-Control"] = "public, max-age=3600"
    return response

"""The public scoreboard of a run, its refreshing fragment and the own place (C4, ADR-0051)."""

from typing import Any
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

from app.api import i18n
from app.api.rendering import mode_bar_of, page
from app.domain import participants, results, rewards
from app.domain.models import Attempt, Participant, QuizRun

POLL_SECONDS = 15


def _reasons() -> dict[str, str]:
    return {
        "hidden": _("The scoreboard is not public."),
        "after_end": _("The scoreboard appears when the run ends."),
        "pending": _("The scoreboard appears when all answers are graded."),
        "archived": _("The results of this run are not public."),
    }


def _run(slug: str, run_id: UUID) -> QuizRun:
    """Normal runs only: `objects` never holds a test run."""
    run = (
        QuizRun.objects.filter(pk=run_id, quiz__slug=slug, quiz__archived_at__isnull=True)
        .select_related("quiz", "current_revision")
        .first()
    )
    if run is None:
        raise Http404
    return run


def _viewer(request: HttpRequest, run: QuizRun) -> Participant | None:
    return participants.find(run, request.COOKIES.get(participants.cookie_name(run), ""))


def _title(run: QuizRun, locale: str) -> str:
    snapshot = run.current_revision.snapshot_json
    return str(snapshot["title"].get(locale) or snapshot["title"].get(snapshot["default_locale"]))


def _context(request: HttpRequest, run: QuizRun, locale: str) -> dict[str, Any]:
    projector = request.GET.get("view") == "projector"
    found = results.board(run, audience="public", locale=locale, viewer=_viewer(request, run))
    rows_url = reverse("scoreboard_rows", args=[run.quiz.slug, run.id])
    query = f"?lang={locale}" + ("&view=projector" if projector else "")
    return {
        "board": found,
        "projector": projector,
        "reason": _reasons().get(found.hidden or ""),
        "poll": not found.final and found.hidden != "archived",
        "poll_seconds": POLL_SECONDS,
        "rows_url": rows_url + query,
        "page_url": reverse("scoreboard", args=[run.quiz.slug, run.id]),
        "locale": locale,
    }


def _cache(request: HttpRequest, response: HttpResponse, run: QuizRun) -> HttpResponse:
    """The own row depends on the cookie, so a page with one is not for a shared cache."""
    if participants.cookie_name(run) in request.COOKIES:
        response["Cache-Control"] = "private, no-store"
    else:
        response["Cache-Control"] = f"public, max-age={results.BOARD_CACHE_SECONDS}"
    return response


def _locale(request: HttpRequest, run: QuizRun) -> str:
    snapshot = run.current_revision.snapshot_json
    return i18n.negotiate(request, snapshot["locales"], snapshot["default_locale"])


def scoreboard(request: HttpRequest, slug: str, run_id: UUID) -> HttpResponse:
    run = _run(slug, run_id)
    locale = _locale(request, run)
    translation.activate(locale)  # the reasons are translated while the context is built
    context = _context(request, run, locale) | {
        "title": _title(run, locale),
        "palette_quiz": run.quiz,
        "mode_bar": None if request.GET.get("view") == "projector" else mode_bar_of(run),
        "quiz_url": reverse("quiz_run", args=[run.quiz.slug, run.id]),
        "winners": rewards.public_winners(run, locale),
    }
    return _cache(request, page(request, "public/scoreboard.html", context, locale), run)


def scoreboard_rows(request: HttpRequest, slug: str, run_id: UUID) -> HttpResponse:
    run = _run(slug, run_id)
    locale = _locale(request, run)
    translation.activate(locale)
    html = render_to_string("public/_scoreboard_rows.html", _context(request, run, locale), request)
    return _cache(request, HttpResponse(html), run)


def url_of(run: QuizRun | None) -> str | None:
    """The public scoreboard, when it shows something."""
    if run is None or run.kind != QuizRun.Kind.NORMAL or not results.is_public(run):
        return None
    return reverse("scoreboard", args=[run.quiz.slug, run.id])


def place_context(attempt: Attempt) -> dict[str, Any]:
    """The own place for a result page, or nothing when the board is not public."""
    if attempt.run.kind != QuizRun.Kind.NORMAL or attempt.pk is None:
        return {}
    place = results.place_of(attempt)
    if place is None:
        return {}
    return {
        "place": place,
        "scoreboard_url": reverse("scoreboard", args=[attempt.run.quiz.slug, attempt.run.id]),
    }

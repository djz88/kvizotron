"""The public scoreboard of a run, its refreshing fragment and the own place (C4, ADR-0051)."""

from typing import Any
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.cache import patch_vary_headers
from django.utils.translation import gettext as _

from app.api import i18n
from app.api.rendering import mode_bar_of, page
from app.contracts import SCOREBOARD_RUNS
from app.domain import participants, results, rewards
from app.domain import settings as quiz_settings
from app.domain.models import Attempt, Participant, Quiz, QuizRun

POLL_SECONDS = 15


def _reasons() -> dict[str, str]:
    return {
        "hidden": _("The scoreboard is not public."),
        "after_end": _("The scoreboard appears when the run ends."),
        "pending": _("The scoreboard appears when all answers are graded."),
        "archived": _("The results of this run are not public."),
        "data_deleted": _("The results of this run are not public."),
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


def _is_admin(request: HttpRequest) -> bool:
    return bool(request.user.is_authenticated)


def _projector(request: HttpRequest) -> bool:
    """Only a signed-in admin gets the projector: it shows the score even where it is hidden."""
    return request.GET.get("view") == "projector" and _is_admin(request)


def _context(request: HttpRequest, run: QuizRun, locale: str) -> dict[str, Any]:
    projector = _projector(request)
    # A shared screen marks nobody, whatever cookie the browser has.
    viewer = None if projector else _viewer(request, run)
    found = results.board(run, audience="public", locale=locale, viewer=viewer)
    rows_url = reverse("scoreboard_rows", args=[run.quiz.slug, run.id])
    query = f"?lang={locale}" + ("&view=projector" if projector else "")
    return {
        "board": found,
        "projector": projector,
        "projector_link": _is_admin(request),
        "reason": _reasons().get(found.hidden or ""),
        "poll": not found.final and found.hidden not in ("archived", "data_deleted"),
        "poll_seconds": POLL_SECONDS,
        "rows_url": rows_url + query,
        "page_url": reverse("scoreboard", args=[run.quiz.slug, run.id]),
        "locale": locale,
    }


def _cache(request: HttpRequest, response: HttpResponse, run: QuizRun) -> HttpResponse:
    """The own row depends on the cookie, so a page with one is not for a shared cache.

    The language (Accept-Language) and the own mark (Cookie) change the answer, so both branches
    vary on them; a `Vary` the response already has is kept (TD-041). What an admin sees (the
    projector and its link) is never for a shared cache either.
    """
    if _is_admin(request) or participants.cookie_name(run) in request.COOKIES:
        response["Cache-Control"] = "private, no-store"
    else:
        response["Cache-Control"] = f"public, max-age={results.BOARD_CACHE_SECONDS}"
    patch_vary_headers(response, ("Accept-Language", "Cookie"))
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
        "branding_quiz": run.quiz,
        "mode_bar": None if _projector(request) else mode_bar_of(run),
        "quiz_url": reverse("quiz_run", args=[run.quiz.slug, run.id]),
        "winners": rewards.public_winners(run, locale),
        "shared_numbers": ", ".join(map(str, results.shared_numbers(run))),
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


def other_boards(quiz: Quiz, shown: QuizRun | None) -> list[dict[str, Any]]:
    """Public boards of the quiz's other runs, newest first, when the admin offers all runs.

    Read live from the quiz on every load; each run still follows its own visibility, and
    `objects` never holds a test run. The template translates the label, in the page's language.
    """
    if quiz_settings.resolve(SCOREBOARD_RUNS, quiz=quiz) != "all":
        return []
    zone = quiz_settings.zone()
    return [
        {
            "url": reverse("scoreboard", args=[quiz.slug, run.id]),
            "number": run.run_no,
            "date": run.opened_at.astimezone(zone).date().isoformat(),  # type: ignore[union-attr]
        }
        for run in results.public_runs(quiz, besides=shown)
    ]


def place_context(attempt: Attempt) -> dict[str, Any]:
    """The own place for a result page, or nothing when the board is not public."""
    if attempt.run.kind != QuizRun.Kind.NORMAL or attempt.pk is None:
        return {}
    place = results.place_of(attempt)
    if place is None:
        return {}
    run = attempt.run
    shared = run.board_main_id is not None or bool(results.shared_numbers(run))
    return {
        "place": place,
        # The place counts only the own run; on a shared board the page says so.
        "place_run": run.run_no if shared else None,
        "scoreboard_url": reverse("scoreboard", args=[attempt.run.quiz.slug, attempt.run.id]),
    }

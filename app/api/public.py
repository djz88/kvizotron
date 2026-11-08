"""Public pages (FR-01, FR-02, FR-03). They read only the published revision of a run."""

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.csp import CSP
from django.utils.translation import gettext as _
from django.views.decorators.csp import csp_override
from django.views.decorators.http import require_POST
from markupsafe import Markup

from app.api import i18n, scoreboard
from app.api.play import MESSAGES, needs_code, rewards_shown
from app.api.rendering import (
    identity_context,
    identity_form,
    media_storage,
    mode_bar_of,
    page,
    question_label,
    reveal_context,
    shows_external_images,
    with_media_urls,
)
from app.contracts import ASK_WHEN, REPEAT_ATTEMPTS, UNFINISHED_ATTEMPT, QuestionTypePlugin
from app.domain import (
    attempts,
    clock,
    data_policy,
    participants,
    reveal,
    rewards,
    run_links,
    selection,
    tokens,
    visibility,
    walkthrough,
)
from app.domain import settings as quiz_settings
from app.domain.models import Attempt, AttemptAnswer, Participant, Quiz, QuizRun
from app.kernel import registry

ASSETS = Path(__file__).parent / "assets"
SERVED_ASSETS = {
    "htmx.min.js": "text/javascript",
    "play.js": "text/javascript",
    "flow.js": "text/javascript",
    "resume.js": "text/javascript",
    "nav.js": "text/javascript",
    "sortable.js": "text/javascript",
    "editor.js": "text/javascript",
    "clock.js": "text/javascript",
    "scoreboard.js": "text/javascript",
    "countdown.js": "text/javascript",
    "planned.js": "text/javascript",
    "flag-cs.svg": "image/svg+xml",
    "flag-en.svg": "image/svg+xml",
    "flag-uk.svg": "image/svg+xml",
    "logo.svg": "image/svg+xml",
    "favicon-32.png": "image/png",
    "apple-touch-icon.png": "image/png",
}


def _title(snapshot: Mapping[str, Any], locale: str) -> str:
    return snapshot["title"].get(locale) or snapshot["title"].get(snapshot["default_locale"], "")


def _description(snapshot: Mapping[str, Any], locale: str) -> str:
    """Revisions published before descriptions existed have none."""
    texts = snapshot.get("description", {})
    return texts.get(locale) or texts.get(snapshot["default_locale"], "")


def landing(request: HttpRequest) -> HttpResponse:
    locale = request.locale  # type: ignore[attr-defined]
    runs = QuizRun.objects.filter(status=QuizRun.Status.OPEN).select_related(
        "quiz", "current_revision"
    )
    quizzes = [
        {
            "slug": run.quiz.slug,
            "title": _title(run.current_revision.snapshot_json, locale),
            "description": _description(run.current_revision.snapshot_json, locale),
            "featured": run.quiz.featured,
        }
        for run in runs.order_by("-quiz__featured", "-opened_at")
    ]
    context = {
        "quizzes": quizzes,
        "coming_up": _coming_up(locale),
        "languages": _languages(i18n.PUBLIC_LOCALES),
    }
    return page(request, "public/landing.html", context, locale)


def _coming_up(locale: str) -> list[dict[str, Any]]:
    """Only what its admin chose to announce, and not a start that has passed without opening."""
    planned = QuizRun.objects.filter(
        status=QuizRun.Status.SCHEDULED, starts_at__gt=timezone.now()
    ).select_related("quiz", "current_revision")
    return [
        {
            "slug": run.quiz.slug,
            "title": _title(run.current_revision.snapshot_json, locale),
            "starts": clock.shown(run.starts_at),
        }
        for run in planned.order_by("starts_at")
        if quiz_settings.resolve(quiz_settings.ANNOUNCE_PLANNED, run.quiz)
        == quiz_settings.Switch.ON
    ]


def info_page(request: HttpRequest, template: str) -> HttpResponse:
    locale = request.locale  # type: ignore[attr-defined]
    context: dict[str, Any] = {"languages": _languages(i18n.PUBLIC_LOCALES)}
    if template == "privacy":
        period = quiz_settings.resolve(quiz_settings.RETENTION_PERIOD)
        labels = quiz_settings.CATALOGUE[quiz_settings.RETENTION_PERIOD].value_labels
        context["retention_period"] = labels[period]
    return page(request, f"public/{template}.html", context, locale)


def _languages(codes: Any) -> list[dict[str, str]]:
    names = dict(settings.LANGUAGES)
    return [{"code": code, "name": names[code]} for code in codes]


def _unavailable(
    request: HttpRequest, message: str, slug: str | None = None, last_run: QuizRun | None = None
) -> HttpResponse:
    """`slug` of a quiz that exists, so a returning participant still finds their result."""
    locale = request.locale  # type: ignore[attr-defined]
    context = {
        "message": message,
        "result_slot": slug,
        "walkthrough_url": _walkthrough_url(last_run),
        "scoreboard_url": scoreboard.url_of(last_run),
    }
    return page(request, "public/unavailable.html", context, locale, status=404)


def quiz(request: HttpRequest, slug: str) -> HttpResponse:
    found = Quiz.objects.filter(slug=slug).first()
    if found is None or found.archived_at is not None:
        return _unavailable(request, _("This quiz does not exist."))
    live = found.runs.filter(status__in=(QuizRun.Status.OPEN, QuizRun.Status.SCHEDULED))
    run = live.select_related("current_revision").first()
    if run is None:
        ended = found.runs.exclude(status=QuizRun.Status.SCHEDULED)
        last_run = ended.select_related("quiz", "current_revision").order_by("-run_no").first()
        message = _("This quiz is not running right now.")
        return _unavailable(request, message, found.slug, last_run)
    return quiz_page(request, run)


def quiz_run(request: HttpRequest, slug: str, run_id: UUID) -> HttpResponse:
    run = (
        QuizRun.objects.filter(pk=run_id, quiz__slug=slug, quiz__archived_at__isnull=True)
        .select_related("current_revision")
        .first()
    )
    if run is None:
        return _unavailable(request, _("This quiz does not exist."))
    return quiz_page(request, run)


def test_link(request: HttpRequest, token: str) -> HttpResponse:
    """One answer for any link that does not work, and never a 404: it would log the path."""
    link = run_links.find_playable(token)
    if link is None:
        locale = request.locale  # type: ignore[attr-defined]
        context = {"message": _("This test link does not work.")}
        response = page(request, "public/unavailable.html", context, locale)
    else:
        response = quiz_page(request, link.run)
    response["X-Robots-Tag"] = "noindex"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _walkthrough_url(run: QuizRun | None) -> str | None:
    if run is None or not walkthrough.available(run):
        return None
    return reverse("walkthrough_page", args=[run.quiz.slug, run.id])


def _short_time(seconds: int) -> str:
    return f"{seconds // 60} min" if seconds >= 60 else f"{seconds} s"


def _time_notice(run: QuizRun) -> dict[str, str | None]:
    """What a participant should know before starting. Starting is never blocked."""
    limit = attempts.limit_for(run)
    deadline = run.deadline_at
    left = int((deadline - timezone.now()).total_seconds()) if deadline else None
    return {
        "limit_text": _short_time(limit) if limit else None,
        "deadline_text": clock.shown(deadline) if deadline else None,
        "shortened_text": (
            _short_time(max(left, 0)) if limit and left is not None and left < limit else None
        ),
    }


def _planned_notice(run: QuizRun) -> dict[str, Any]:
    """A start that passed without opening has no time to promise, and the admin sees why."""
    if run.status != QuizRun.Status.SCHEDULED or run.starts_at is None:
        return {"planned": False}
    seconds = int((run.starts_at - timezone.now()).total_seconds())
    ahead = seconds > 0
    return {
        "planned": True,
        "starts_text": clock.shown(run.starts_at) if ahead else None,
        "starts_in": seconds if ahead else None,
    }


def quiz_page(
    request: HttpRequest, run: QuizRun, *, code_error: str | None = None, status: int = 200
) -> HttpResponse:
    snapshot = run.current_revision.snapshot_json
    locale = i18n.negotiate(request, snapshot["locales"], snapshot["default_locale"])
    rules = participants.rules_of(run)
    context = {
        "title": _title(snapshot, locale),
        "description": _description(snapshot, locale),
        "palette_quiz": run.quiz,
        "mode_bar": mode_bar_of(run),
        "run": run,
        "is_open": run.status == QuizRun.Status.OPEN,
        "code_needed": needs_code(request, run),
        "may_restart": rules.get(REPEAT_ATTEMPTS) == "allow"
        or rules.get(UNFINISHED_ATTEMPT) == "submitted",
        "code_error": code_error,
        "identity": identity_context(rules) if rules.get(ASK_WHEN, "end") == "start" else None,
        **_time_notice(run),
        **_planned_notice(run),
        "question_count": selection.count(snapshot),
        "languages": _languages(snapshot["locales"]),
        "result_slot": run.quiz.slug if run.kind == QuizRun.Kind.NORMAL else None,
        "walkthrough_url": _walkthrough_url(run),
        "scoreboard_url": scoreboard.url_of(run),
        "stateless": data_policy.is_stateless(attempts.effective_profile(run)),
        "offered": rewards.offered(run, locale),
    }
    return page(request, "public/quiz.html", context, locale, status=status)


def _private(response: HttpResponse) -> HttpResponse:
    """Holds a working address, and what it shows may be taken back at any moment."""
    response["X-Robots-Tag"] = "noindex"
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "private, no-store"
    return response


def _attempt_of_token(token: str) -> Attempt | None:
    try:
        attempt_id = tokens.verify_result(token)
    except tokens.InvalidToken:
        return None
    return (
        Attempt.objects.filter(pk=attempt_id, status__in=Attempt.FINISHED)
        .select_related("run", "run__quiz", "revision")
        .first()
    )


def _own_answer(
    question: Mapping[str, Any], row: AttemptAnswer, attempt: Attempt, token: str, locale: str
) -> dict[str, Any]:
    plugin = cast(
        QuestionTypePlugin, registry.get("question_type", question["type"], include_disabled=True)
    )
    shown: dict[str, Any] = {
        "prompt": question_label(question, locale),
        "removed": row.removed,
        "photo": None,
        "labels": [],
        "reveal": None,
    }
    if plugin.file_fields(question["definition"]):
        if visibility.author_sees_photo(row, attempt.run.quiz, question):
            shown["photo"] = reverse("result_photo", args=[token, row.id])
        if row.manual_points is not None and not row.removed:
            shown["points"] = row.auto_points + row.manual_points
            shown["maximum"] = row.auto_points + row.manual_max
        return shown
    if not visibility.participant_sees_answers(attempt):
        return {}
    summary = plugin.summarize(question["definition"], [row.answer_json], locale)
    shown["labels"] = [item.label for item in summary]
    flow = attempts.flow_of(attempt)
    if flow["moment"] != quiz_settings.RevealMoment.NEVER:
        with translation.override(locale):
            revealed = reveal.of_question(question, row.answer_json, flow["level"], locale)
            quiz = attempt.run.quiz
            shown["reveal"] = reveal_context(
                question, revealed, row.answer_json, locale, with_prompt=False, quiz=quiz
            )
    return shown


def _own_answers(attempt: Attempt, token: str, locale: str) -> list[dict[str, Any]]:
    rows = {row.question_id: row for row in attempt.answers.all()}
    found = []
    for question in attempts.questions_of(attempt):
        row = rows.get(question["id"])
        if row is None:
            continue
        try:
            shown = _own_answer(question, row, attempt, token, locale)
        except registry.UnknownPort, attempts.AttemptError:
            continue
        if shown and (shown["photo"] or shown["removed"] or shown["labels"]):
            found.append(shown)
    return found


def _unavailable_answers(request: HttpRequest) -> HttpResponse:
    locale = request.locale  # type: ignore[attr-defined]
    context = {"message": _("This walkthrough is not available.")}
    return _private(page(request, "public/unavailable.html", context, locale))


def _ended_run(slug: str, run_id: UUID) -> QuizRun | None:
    return (
        QuizRun.objects.filter(pk=run_id, quiz__slug=slug)
        .select_related("quiz", "current_revision")
        .first()
    )


def _walkthrough_item(
    item: walkthrough.WalkthroughQuestion,
    run: QuizRun,
    locale: str,
    *,
    answers: bool,
    is_admin: bool,
) -> dict[str, Any]:
    question = item.question
    plugin = cast(
        QuestionTypePlugin, registry.get("question_type", question["type"], include_disabled=True)
    )
    external = shows_external_images(run.quiz, question)
    definition = with_media_urls(question["definition"], external=external)
    image = definition.get("image")
    counts = [
        {
            "key": row.count.key,
            "label": row.count.label,
            "count": row.count.count,
            "hidden": row.hidden,
        }
        for row in item.counts
        if is_admin or not row.hidden
    ]
    shown: dict[str, Any] = {
        "id": question["id"],
        "prompt": question_label(question, locale),
        "image": {"url": image.get("url", ""), "alt": image["alt"].get(locale, "")}
        if image
        else None,
        "counts": counts,
        "photos": [
            reverse("walkthrough_photo", args=[run.quiz.slug, run.id, row.id])
            for row in item.photos
        ],
        "solution": None,
        "explanation": None,
    }
    if answers and not plugin.file_fields(question["definition"]):
        with translation.override(locale):
            shown["solution"] = Markup(  # noqa: S704  # the plugin escapes through its own template
                plugin.render_solution(definition, locale, None)
            )
    if answers:
        shown["explanation"] = question.get("explanation", {}).get(locale) or None
    return shown


def walkthrough_page(request: HttpRequest, slug: str, run_id: UUID) -> HttpResponse:
    """One plain message whenever it is not available, so it says nothing about the run."""
    run = _ended_run(slug, run_id)
    if run is None or not walkthrough.available(run):
        return _unavailable_answers(request)
    snapshot = run.current_revision.snapshot_json
    locale = i18n.negotiate(request, snapshot["locales"], snapshot["default_locale"])
    is_admin = request.user.is_authenticated
    answers = walkthrough.shows_answers(run)
    context = {
        "title": _title(snapshot, locale),
        "palette_quiz": run.quiz,
        "run": run,
        "is_admin": is_admin,
        "items": [
            _walkthrough_item(item, run, locale, answers=answers, is_admin=is_admin)
            for item in walkthrough.of_run(run, locale)
        ],
    }
    return _private(page(request, "public/walkthrough.html", context, locale))


def walkthrough_photo(
    request: HttpRequest, slug: str, run_id: UUID, answer_id: UUID
) -> HttpResponse:
    """A refusal is 204, as on the private link, so nobody learns which photos exist."""
    run = _ended_run(slug, run_id)
    row = walkthrough.photo_for_public(run, answer_id) if run is not None else None
    if row is None:
        return _private(HttpResponse(status=204))
    return _private(_private_file(row.asset_id))


def result(request: HttpRequest, token: str) -> HttpResponse:
    """One answer for any link that does not work, and never a 404: it would log the path."""
    attempt = _attempt_of_token(token)
    if attempt is None:
        return _no_such_result(request)
    return _result_page(request, attempt, token)


def _no_such_result(request: HttpRequest) -> HttpResponse:
    locale = request.locale  # type: ignore[attr-defined]
    context = {"message": _("This link does not work.")}
    return _private(page(request, "public/unavailable.html", context, locale))


def _result_page(
    request: HttpRequest, attempt: Attempt, token: str, error: str | None = None, status: int = 200
) -> HttpResponse:
    snapshot = attempt.revision.snapshot_json
    locale = i18n.negotiate(request, snapshot["locales"], snapshot["default_locale"])
    form = identity_form(attempt)
    if form is not None and error:  # what was typed stays, except where it was refused
        form |= {
            "name_value": request.POST.get("participant_name", ""),
            "email_value": request.POST.get("participant_email", ""),
        }
    maximum = attempt.max_score or Decimal(0)
    score = attempt.score or Decimal(0)
    context = {
        "title": _title(snapshot, locale),
        "palette_quiz": attempt.run.quiz,
        "mode_bar": mode_bar_of(attempt.run),
        "earned": score,
        "maximum": maximum,
        "percentage": round(float(score / maximum * 100), 2) if maximum else 0,
        "pending": attempt.status == Attempt.Status.PENDING_GRADING,
        "answers": _own_answers(attempt, token, locale),
        "identity_form": form,
        "identity_error": error,
        "rewards": rewards_shown(attempt, locale),
        **scoreboard.place_context(attempt),
    }
    return _private(page(request, "public/result.html", context, locale, status=status))


@require_POST
def result_identity(request: HttpRequest, token: str) -> HttpResponse:
    """Fills in only what is still missing. Refused once the run is archived."""
    attempt = _attempt_of_token(token)
    if attempt is None:
        return _no_such_result(request)
    snapshot = attempt.revision.snapshot_json
    locale = i18n.negotiate(request, snapshot["locales"], snapshot["default_locale"])
    if attempt.run.status == QuizRun.Status.ARCHIVED:
        with translation.override(locale):
            message = _("This run is archived, so the details can no longer be added.")
        return _result_page(request, attempt, token, str(message))
    try:
        if attempt.participant_id is not None:
            _fill_in(request, attempt)
    except attempts.AttemptError as error:
        with translation.override(locale):
            message = str(MESSAGES[error.code])
        return _result_page(request, attempt, token, message)
    return _private(HttpResponseRedirect(f"{reverse('result', args=[token])}?lang={locale}"))


def _fill_in(request: HttpRequest, attempt: Attempt) -> None:
    attempts.with_retry(lambda: _write_identity(request, attempt))


def _write_identity(request: HttpRequest, attempt: Attempt) -> None:
    with transaction.atomic():
        participant = Participant.objects.get(pk=attempt.participant_id)
        raw_name = participant.display_name or request.POST.get("participant_name", "")
        raw_email = participant.email or request.POST.get("participant_email", "")
        identity = participants.read_identity(
            participants.rules_of(attempt.run), raw_name, raw_email, automatic=False
        )
        participants.claim_name(participant, identity, automatic=False)
        Participant.objects.filter(pk=participant.pk).update(name_dropped=False)


def result_photo(request: HttpRequest, token: str, answer_id: UUID) -> HttpResponse:
    """A refusal is 204, because a 4xx would log the path, and the token is in it."""
    attempt = _attempt_of_token(token)
    row = attempt.answers.filter(pk=answer_id).first() if attempt else None
    question = None
    if attempt is not None and row is not None:
        question = next(
            (q for q in attempts.questions_of(attempt) if q["id"] == row.question_id), None
        )
    if (
        attempt is None
        or row is None
        or question is None
        or not visibility.author_sees_photo(row, attempt.run.quiz, question)
    ):
        return _private(HttpResponse(status=204))
    return _private(_private_file(row.asset_id))


def _private_file(asset_id: str | None) -> HttpResponse:
    storage = media_storage()
    stored = storage.load(str(asset_id)) if storage and asset_id else None
    if stored is None:
        return HttpResponse(status=204)
    return FileResponse(Path(stored.path).open("rb"), content_type=stored.mime_type)


@csp_override({"default-src": [CSP.NONE], "sandbox": True})
def media(request: HttpRequest, asset_id: UUID) -> FileResponse:
    """The policy applies when a file is opened directly: an SVG shown that way runs nothing."""
    storage = media_storage()
    stored = storage.load(str(asset_id)) if storage else None
    if stored is None or stored.private:
        raise Http404
    response = FileResponse(Path(stored.path).open("rb"), content_type=stored.mime_type)
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def asset(request: HttpRequest, name: str) -> FileResponse:
    if name not in SERVED_ASSETS:
        raise Http404
    response = FileResponse((ASSETS / name).open("rb"), content_type=SERVED_ASSETS[name])
    response["Cache-Control"] = "public, max-age=3600"
    return response

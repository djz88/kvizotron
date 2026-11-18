"""The quiz type of one quiz: the overview before applying it, applying and removing (ADR-0062).

What a type writes, adjusts, skips or refuses is decided by `app.domain.quiz_types`; this only
names it.
"""

from typing import Any
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from app.api.admin_auth import admin_required
from app.api.admin_forms import clash_message, setting_label, setting_value_label
from app.api.admin_quizzes import not_archived, run_offer_context
from app.api.admin_workspace import quiz_title
from app.api.rendering import page
from app.domain import quiz_types, run_flow_change, settings
from app.domain.models import Quiz


def _change(change: quiz_types.Change) -> dict[str, str]:
    if change.new is None:
        now = setting_value_label(change.key, settings.resolve(change.key))
        new = _("global value (now: %(value)s)") % {"value": now}
    else:
        new = setting_value_label(change.key, change.new)
    return {
        "label": setting_label(change.key),
        "current": setting_value_label(change.key, change.current),
        "new": new,
    }


def _overview(
    request: HttpRequest, quiz: Quiz, shown: quiz_types.Preview, status: int = 200
) -> HttpResponse:
    plugin = quiz_types.get(shown.type_id)
    context: dict[str, Any] = {
        "quiz": quiz,
        "title": quiz_title(quiz),
        "type_id": shown.type_id,
        "type_label": plugin.label() if plugin else shown.type_id,
        "again": shown.type_id == quiz.quiz_type,
        "changes": [_change(change) for change in shown.changes],
        "adjusted": [_change(change) for change in shown.adjusted],
        "skipped": [setting_label(key) for key in shown.skipped],
        "refused": list(dict.fromkeys(clash_message(clash) for clash in shown.refused)),
        "run_offer": run_offer_context(shown.run_offer) if shown.run_offer else None,
        "content": [setting_label(key) for key in shown.content],
    }
    return page(
        request,
        "admin/quiz_type_confirm.html",
        context,
        request.locale,  # type: ignore[attr-defined]
        status=status,
    )


@admin_required
@not_archived
@require_http_methods(["GET", "POST"])
def quiz_type(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """GET `?type=` and POST without `confirm` show the overview; a confirmed POST applies."""
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    source = request.POST if request.method == "POST" else request.GET
    type_id = source.get("type", "")
    try:
        if request.method == "POST" and request.POST.get("confirm") == "1":
            try:
                quiz_types.apply(
                    quiz,
                    type_id,
                    admin_id=str(request.user.pk),
                    flow_choice=request.POST.get(run_flow_change.FIELD),
                )
            except (
                quiz_types.TypeRefused,
                run_flow_change.ChoiceNeeded,
                run_flow_change.FlowRefused,
            ) as refusal:
                quiz.refresh_from_db()  # apply set the type in memory before the rollback
                status = 400 if isinstance(refusal, run_flow_change.ChoiceNeeded) else 409
                return _overview(request, quiz, quiz_types.preview(quiz, type_id), status=status)
            return redirect("admin_quiz_settings", quiz.id)
        return _overview(request, quiz, quiz_types.preview(quiz, type_id))
    except quiz_types.UnknownType as error:
        raise Http404 from error


@admin_required
@not_archived
@require_POST
def quiz_type_remove(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """Forgets the type; every value stays."""
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    quiz_types.remove(quiz, admin_id=str(request.user.pk))
    return redirect("admin_quiz_settings", quiz.id)

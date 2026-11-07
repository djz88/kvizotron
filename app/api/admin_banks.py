"""Question banks, and the rows of a quiz that draw from them."""

import secrets
import uuid
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from markupsafe import Markup

from app.api import rendering
from app.api.admin_auth import admin_required
from app.api.admin_forms import BankForm, BankQuestionForm, DrawForm
from app.api.admin_quizzes import (
    _add_menu,
    _enabled_plugin,
    _strategies,
    not_archived,
    read_question_form,
    setting_initial,
)
from app.api.i18n import PUBLIC_LOCALES
from app.api.rendering import page, question_label, with_media_urls
from app.contracts import QuestionTypePlugin
from app.domain import authoring, banks
from app.domain.models import BankQuestion, QuestionBank, Quiz
from app.domain.questions import has_image_without_copy


def _bank_page(
    request: HttpRequest, bank: QuestionBank, error: str | None = None, status: int = 200
) -> HttpResponse:
    questions = [
        {
            "id": row.pk,
            "label": question_label(row.question_json, PUBLIC_LOCALES[0]),
            "tags": row.tags,
            "complete": banks.complete_locales(row, PUBLIC_LOCALES),
            "no_copy": has_image_without_copy(row.question_json),
        }
        for row in bank.questions.order_by("id")
    ]
    context = {
        "can_import": rendering.can_import(),
        "bank": bank,
        "form": BankForm(initial={"name": bank.name}),
        "questions": questions,
        "question_types": _add_menu(),
        "error": error,
    }
    return page(request, "admin/bank.html", context, request.locale, status=status)  # type: ignore[attr-defined]


@admin_required
def banks_page(request: HttpRequest) -> HttpResponse:
    form = BankForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        bank = banks.create(form.cleaned_data["name"], admin_id=str(request.user.pk))
        return redirect("admin_bank", bank.id)
    context = {
        "form": form,
        "banks": [
            {"bank": bank, "count": bank.questions.count()}
            for bank in QuestionBank.objects.order_by("name")
        ],
    }
    return page(request, "admin/banks.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
def bank_page(request: HttpRequest, bank_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    if request.method == "POST":
        form = BankForm(request.POST)
        if form.is_valid():
            banks.rename(bank, form.cleaned_data["name"], admin_id=str(request.user.pk))
        return redirect("admin_bank", bank.id)
    return _bank_page(request, bank)


@admin_required
@require_POST
def bank_delete(request: HttpRequest, bank_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    try:
        banks.delete(bank, admin_id=str(request.user.pk))
    except banks.BankInUse as error:
        message = _("This bank is used by these quizzes: %(quizzes)s") % {
            "quizzes": ", ".join(error.quizzes)
        }
        return _bank_page(request, bank, message, status=409)
    return redirect("admin_banks")


def _question_page(
    request: HttpRequest,
    bank: QuestionBank,
    plugin: QuestionTypePlugin,
    config: Any,
    common: BankQuestionForm,
    form_key: str | None,
    error: str | None = None,
) -> HttpResponse:
    context = {
        "type_label": plugin.label(),
        "editor": Markup(  # noqa: S704  # the plugin escapes through its own template
            plugin.render_admin(with_media_urls(config, keep_asset=True), PUBLIC_LOCALES)
        ),
        "common_form": common,
        "form_key": form_key,
        "error": error,
        "back_url": reverse("admin_bank", args=[bank.id]),
        "editor_kind": "bank",
    }
    return page(request, "admin/question_form.html", context, request.locale)  # type: ignore[attr-defined]


def _save_question(
    request: HttpRequest,
    bank: QuestionBank,
    plugin: QuestionTypePlugin,
    question_id: str | None,
    current: Any,
) -> HttpResponse:
    common = BankQuestionForm(
        request.POST, strategies=_strategies(plugin), locales=PUBLIC_LOCALES, plugin=plugin
    )
    key = request.POST.get("form_key", "") if question_id is None else None
    config, message = read_question_form(request, plugin, PUBLIC_LOCALES, current)
    if message or not common.is_valid():
        return _question_page(request, bank, plugin, config, common, key, message)
    try:
        banks.save_question(
            bank,
            question_id,
            plugin.id,
            config,
            locales=PUBLIC_LOCALES,
            tags=common.cleaned_data["tags"],
            scoring=common.cleaned_data["scoring"] or None,
            sources=common.cleaned_data["sources"],
            explanation=common.explanation(),
            new_id=str(uuid.uuid5(bank.id, key)) if key else None,
            admin_id=str(request.user.pk),
            setting_values=common.setting_values(),
        )
    except banks.NoCompleteLanguage:
        message = _("Complete the question in at least one language.")
        return _question_page(request, bank, plugin, config, common, key, message)
    return redirect("admin_bank", bank.id)


@admin_required
def bank_question_new(request: HttpRequest, bank_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    plugin = _enabled_plugin(request.GET.get("type", ""))
    if request.method == "POST":
        return _save_question(request, bank, plugin, None, {})
    config = plugin.initial(request.GET.get("preset", ""), PUBLIC_LOCALES)
    common = BankQuestionForm(strategies=_strategies(plugin), locales=PUBLIC_LOCALES, plugin=plugin)
    return _question_page(request, bank, plugin, config, common, secrets.token_urlsafe(16))


@admin_required
def bank_question_edit(request: HttpRequest, bank_id: UUID, question_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    row = get_object_or_404(BankQuestion, pk=question_id, bank=bank)
    question = row.question_json
    plugin = _enabled_plugin(question["type"])
    if request.method == "POST":
        return _save_question(request, bank, plugin, str(row.pk), question["definition"])
    initial = {
        "scoring": question["scoring"],
        "sources": "\n".join(question.get("sources", [])),
        "tags": ", ".join(row.tags),
        **setting_initial(question),
        **{
            f"explanation_{locale}": text
            for locale, text in question.get("explanation", {}).items()
        },
    }
    common = BankQuestionForm(
        initial=initial, strategies=_strategies(plugin), locales=PUBLIC_LOCALES, plugin=plugin
    )
    return _question_page(request, bank, plugin, question["definition"], common, None)


@admin_required
@require_POST
def bank_question_delete(request: HttpRequest, bank_id: UUID, question_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    banks.delete_question(bank, question_id, admin_id=str(request.user.pk))
    return redirect("admin_bank", bank.id)


def _bank_choices() -> Sequence[tuple[str, str]]:
    return [(str(bank.id), bank.name) for bank in QuestionBank.objects.order_by("name")]


def _all_tags() -> list[str]:
    tags = {tag for bank in QuestionBank.objects.all() for tag in banks.tags_of(bank)}
    return sorted(tags, key=banks.normal_tag)


def _draw_form(quiz: Quiz, *args: Any, **kwargs: Any) -> DrawForm:
    return DrawForm(
        *args,
        banks=_bank_choices(),
        own_questions=len(authoring.editable_questions(quiz)),
        tags=_all_tags(),
        **kwargs,
    )


def _draw_page(request: HttpRequest, quiz: Quiz, form: DrawForm) -> HttpResponse:
    context = {"quiz": quiz, "form": form, "has_banks": bool(_bank_choices())}
    return page(request, "admin/draw_form.html", context, request.locale)  # type: ignore[attr-defined]


def _save_draw(request: HttpRequest, quiz: Quiz, draw_id: str | None) -> HttpResponse:
    form = _draw_form(quiz, request.POST)
    if not form.is_valid():
        return _draw_page(request, quiz, form)
    data = form.cleaned_data
    authoring.save_draw(
        quiz,
        draw_id,
        bank_id=data["bank"],
        tag=data["tag"],
        count=data["count"],
        points=data["points"],
        position=data["position"],
    )
    return redirect("admin_quiz_edit", quiz.id)


@admin_required
@not_archived
def draw_new(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    if request.method == "POST":
        return _save_draw(request, quiz, None)
    initial = {"count": 5, "points": 1, "position": len(authoring.editable_questions(quiz))}
    return _draw_page(request, quiz, _draw_form(quiz, initial=initial))


def _existing_draw(quiz: Quiz, draw_id: str) -> dict[str, Any]:
    for row in authoring.editable_draws(quiz):
        if row["id"] == draw_id:
            return row
    raise Http404


@admin_required
@not_archived
def draw_edit(request: HttpRequest, quiz_id: UUID, draw_id: str) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    row = _existing_draw(quiz, draw_id)
    if request.method == "POST":
        return _save_draw(request, quiz, draw_id)
    initial = {
        "bank": row["bank_id"],
        "tag": row["tag"],
        "count": row["count"],
        "points": row["points"],
        "position": row["position"],
    }
    return _draw_page(request, quiz, _draw_form(quiz, initial=initial))


@admin_required
@not_archived
@require_POST
def draw_delete(request: HttpRequest, quiz_id: UUID, draw_id: str) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    _existing_draw(quiz, draw_id)
    authoring.delete_draw(quiz, draw_id)
    return redirect("admin_quiz_edit", quiz.id)

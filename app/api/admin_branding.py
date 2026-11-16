"""Name, motto, logo and footer of the pages, for the application and for one quiz (FR-53)."""

from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from app.api import admin_quizzes, admin_settings
from app.api.admin_auth import admin_required
from app.api.admin_forms import BrandingForm
from app.contracts import ImageRefused
from app.domain import branding
from app.domain.models import Quiz


def _save(request: HttpRequest, quiz: Quiz | None) -> BrandingForm | None:
    """None when it was saved; otherwise the form with what to correct."""
    admin_id = str(request.user.pk)
    cleared = request.POST.get("clear", "")
    if cleared == "logo":
        branding.remove_logo(quiz, admin_id=admin_id)
        return None
    if cleared == "hero_logo":
        branding.remove_hero_logo(quiz, admin_id=admin_id)
        return None
    if cleared == branding.CONTACT_EMAIL:
        branding.set_contact_email(quiz, "", admin_id=admin_id)
        return None
    if cleared in branding.TEXT_LIMITS:
        branding.set_texts(quiz, cleared, {}, admin_id=admin_id)
        return None
    form = BrandingForm(request.POST, request.FILES, quiz=quiz)
    if not form.is_valid():
        return form
    try:
        form.save(admin_id)
    except ImageRefused:
        return form
    return None


@admin_required
@require_POST
def global_branding(request: HttpRequest) -> HttpResponse:
    form = _save(request, None)
    if form is None:
        return redirect("admin_settings")
    return admin_settings.settings_page(request, branding_form=form)


@admin_required
@require_POST
@admin_quizzes.not_archived
def quiz_branding(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    form = _save(request, quiz)
    if form is None:
        return redirect("admin_quiz_settings", quiz.id)
    return admin_quizzes.settings_page(request, quiz, branding_form=form)

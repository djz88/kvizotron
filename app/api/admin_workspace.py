"""What every page of one quiz shows above its content: status, next steps and tabs."""

from typing import Any

from django.urls import reverse
from django.utils.translation import gettext as _

from app.api import rendering
from app.api.admin_forms import setting_value_label
from app.api.inline_name import NameField
from app.api.rendering import media_storage
from app.domain import clock, external_images, grading, quiz_state, quiz_types, requirements
from app.domain.models import Quiz


def quiz_title(quiz: Quiz) -> str:
    return quiz.title.get(quiz.default_locale) or quiz.slug


def name_field(
    quiz: Quiz,
    *,
    editing: bool = False,
    value: str | None = None,
    error: str = "",
    saved: bool = False,
) -> NameField:
    """The title in the default language, edited on the spot; the others are in the settings."""
    edit_url = reverse("admin_quiz_edit", args=[quiz.id])
    name_url = reverse("admin_quiz_name", args=[quiz.id])
    return NameField(
        label=_("Title"),
        field="name",
        key=str(quiz.id),
        value=quiz_title(quiz) if value is None else value,
        save_url=name_url,
        edit_url=f"{name_url}?edit=1",
        view_url=name_url,
        edit_page=f"{edit_url}?edit=name",
        back_page=edit_url,
        max_length=200,
        editing=editing,
        error=error,
        note=_("Visitors see the new name after you publish."),
        saved=saved,
        mirror=f"quiz-title-{quiz.id}",
        tag="h1",
    )


def image_check(quiz: Quiz) -> dict[str, Any]:
    """The stored results, so that a tab opened within the hour still warns."""
    addresses = external_images.addresses_of(quiz)
    storage = media_storage()
    status = storage.address_status(addresses) if storage and addresses else {}
    checked = [item.checked_at for item in status.values()]
    return {
        "addresses": addresses,
        "failed": [address for address, item in status.items() if not item.ok],
        "checked_at": clock.shown(max(checked)) if checked else None,
    }


def type_bar(quiz: Quiz) -> dict[str, Any]:
    """The quiz type above the settings and the marks beside each field that deviates from it.

    A type of a disabled or missing module keeps its name (or id) and offers only Remove; its
    deviations are not shown, since the type cannot be applied again (ADR-0062).
    """
    offered = quiz_types.available()
    plugin = quiz_types.get(quiz.quiz_type) if quiz.quiz_type else None
    active = any(item.id == quiz.quiz_type for item in offered)
    deviations = quiz_types.deviations(quiz) if active else {}
    marks = {
        key: setting_value_label(key, value) if value is not None else _("global value")
        for key, value in deviations.items()
    }
    return {
        "id": quiz.quiz_type,
        "label": plugin.label() if plugin else quiz.quiz_type,
        "active": active,
        "count": len(deviations),
        "offered": [(item.id, item.label()) for item in offered],
        "others": [(item.id, item.label()) for item in offered if item.id != quiz.quiz_type],
        "marks": marks,
    }


def workspace(quiz: Quiz, tab: str, run_error: str | None = None) -> dict[str, Any]:
    """`tab` is the last part of its address: `edit`, `runs`, `grading` and so on."""
    return {
        "quiz": quiz,
        "title": quiz_title(quiz),
        "name_field": name_field(quiz),
        "tab": tab,
        "can_import": rendering.can_import(),
        "run_error": run_error,
        "state": quiz_state.of(quiz),
        "image_check": image_check(quiz),
        "requirements": requirements.unmet(quiz),
        "waiting": grading.waiting_in_quiz(quiz),
    }

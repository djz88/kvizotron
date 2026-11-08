"""The "Basic / All" switch and the setting groups shared by every settings page (ADR-0052)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from django import forms
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from app.api.admin_auth import admin_required
from app.contracts import BASIC, SETTING_GROUPS
from app.domain import settings

COOKIE = "kvz_admin_view"
ALL = "all"
YEAR = 365 * 24 * 3600
GROUP_LABELS = {
    "playing": gettext_lazy("Playing"),
    "answers": gettext_lazy("Answers and result"),
    "participants": gettext_lazy("Participants"),
    "scoreboard": gettext_lazy("Scoreboard"),
    "data": gettext_lazy("Data"),
    "look": gettext_lazy("Look and listing"),
    "technical": gettext_lazy("Technical"),
}


def is_basic(request: HttpRequest) -> bool:
    """Basic unless the admin chose All; the choice only shows or hides, it never decides."""
    return request.COOKIES.get(COOKIE) != ALL


@admin_required
@require_POST
def switch(request: HttpRequest) -> HttpResponse:
    mode = ALL if request.POST.get("mode") == ALL else BASIC
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = "/admin/"
    response = redirect(target)
    response.set_cookie(
        COOKIE, mode, max_age=YEAR, samesite="Lax", secure=request.is_secure(), httponly=True
    )
    return response


@dataclass
class FieldGroup:
    key: str
    label: str
    fields: list[forms.BoundField] = field(default_factory=list)
    hidden: int = 0
    open: bool = False  # holds an error or a value that differs from what it inherits


def group_fields(
    form: forms.Form,
    *,
    basic: bool,
    differs: Callable[[str], bool],
    extra: Mapping[str, tuple[str, str]] | None = None,
    skip: tuple[str, ...] = (),
) -> list[FieldGroup]:
    """The form's settings in the global group order; other fields are left to the page.

    `extra` places a field that is not a catalogue setting as (group, level). A field is shown
    when the view is All, when it is basic, when its value differs, or when it was refused.
    """
    groups = {key: FieldGroup(key, str(GROUP_LABELS[key])) for key in SETTING_GROUPS}
    for bound in form:
        if bound.name in skip:
            continue
        definition = settings.CATALOGUE.get(bound.name)
        if definition is not None:
            place: tuple[str, str] | None = (definition.group, definition.level)
        else:
            place = (extra or {}).get(bound.name)
        if place is None:
            continue
        group = groups[place[0]]
        changed = differs(bound.name)
        if bound.errors or changed:
            group.open = True
        if not basic or place[1] == BASIC or changed or bound.errors:
            group.fields.append(bound)
        else:
            group.hidden += 1
    return [group for group in groups.values() if group.fields or group.hidden]


def outside_groups(
    form: forms.Form, *, extra: Mapping[str, tuple[str, str]] | None = None
) -> list[forms.BoundField]:
    """Fields that are not settings, such as a quiz's address, which the page shows first."""
    return [
        bound
        for bound in form
        if bound.name not in settings.CATALOGUE and bound.name not in (extra or {})
    ]

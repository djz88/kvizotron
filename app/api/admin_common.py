"""Small helpers the admin views share (one copy each)."""

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.utils.translation import gettext as _

from app.api.rendering import page


def admin_id(request: HttpRequest) -> str:
    """The signed-in admin as the text the domain services take."""
    return str(request.user.pk)


def uuid_or_404(value: str) -> UUID:
    """A posted or routed id; anything that is not a UUID is a missing page."""
    try:
        return UUID(value)
    except ValueError:
        raise Http404 from None


def plain(value: Decimal | None, *, none: str = "") -> str:
    """A number without exponent or trailing zeros; `none` stands in for no value."""
    return none if value is None else f"{value.normalize():f}"


def locale_of(request: HttpRequest) -> str:
    return cast(str, request.locale)  # type: ignore[attr-defined]


# Refusals of the run plan, deadline, period and data deletion, by domain code
def refusal(code: str) -> str:
    """The message of a refused run change; an unknown code gets the general one."""
    messages = {
        "start_in_past": _("The start has already passed."),
        "deadline_before_start": _("The deadline must be after the start."),
        "already_planned": _("This quiz already has a running or planned run."),
        "not_planned": _("This run is no longer planned."),
        "deadline_too_soon": _("The deadline must be at least a minute ahead."),
        "not_open": _("This run has ended."),
        "data_deleted": _("The data of this run were deleted, so its period cannot change."),
        "not_ended": _("Data can be deleted only after the run has ended."),
    }
    return messages.get(code, _("This cannot be done now."))


def confirm_page(
    request: HttpRequest,
    *,
    message: str,
    action: str,
    cancel: str | None = None,
    quiz: Any = None,
    hidden: dict[str, str] | None = None,
    repeated: list[tuple[str, str]] | None = None,
) -> HttpResponse:
    """`admin/confirm.html`; a key left out of the call is left out of the context."""
    optional = {"quiz": quiz, "cancel": cancel, "hidden": hidden, "repeated": repeated}
    context = {"message": message, "action": action}
    context |= {key: value for key, value in optional.items() if value is not None}
    return page(request, "admin/confirm.html", context, locale_of(request))

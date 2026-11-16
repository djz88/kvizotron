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
from app.contracts import BASIC, SETTING_GROUPS, DerivedPalette
from app.domain import bank_folders, branding, settings
from app.domain.models import Quiz

COOKIE = "kvz_admin_view"
ALL = "all"
YEAR = 365 * 24 * 3600
GROUP_LABELS = {
    "playing": gettext_lazy("Playing"),
    "answers": gettext_lazy("Answers and result"),
    "participants": gettext_lazy("Participants"),
    "scoreboard": gettext_lazy("Scoreboard"),
    "rewards": gettext_lazy("Rewards"),
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
    children: set[str] = field(default_factory=set)  # drawn indented under their parent
    columns: dict[str, str] = field(default_factory=dict)  # scoreboard column: its short label
    unmatched: set[str] = field(default_factory=set)  # drawn `hidden` by a search, still sent
    matched: bool = True  # False: a search found nothing here, the group is drawn `hidden`


# A setting that only matters with the one it follows is drawn under it, indented (AC-168).
CHILD_OF = {
    "page_size": "navigation_mode",
    "reveal_level": "reveal_moment",
    "duplicate_names": "ask_name",
    "max_attempts": "repeat_attempts",
    "after_pass": "max_attempts",
    "scoreboard_live_names": "scoreboard_visibility",
    "scoreboard_unnamed": "scoreboard_visibility",
    "main": "color_palette",
    "accent": "color_palette",
}
KEEP_ORDER_UNDER = {"color_palette"}  # main before accent, as on the colour wheel of the form

# The four scoreboard columns are one block with short labels; it sorts as its legend.
COLUMNS = (
    "scoreboard_show_score",
    "scoreboard_show_percent",
    "scoreboard_show_time",
    "scoreboard_show_duration",
)
COLUMNS_LEGEND = gettext_lazy("Scoreboard columns")
COLUMN_LABELS = {
    "scoreboard_show_score": gettext_lazy("Score"),
    "scoreboard_show_percent": gettext_lazy("Percent"),
    "scoreboard_show_time": gettext_lazy("Time submitted"),
    "scoreboard_show_duration": gettext_lazy("Duration"),
}
MAX_RADIOS = 3  # more values, not counting "use global", stay a dropdown


def _as_radios(field: forms.Field) -> None:
    """A short choice is shown as radio buttons in a row; the submitted values stay the same."""
    if not isinstance(field, forms.ChoiceField) or type(field.widget) is not forms.Select:
        return
    choices = list(field.choices)
    if len([value for value, _label in choices if value != ""]) > MAX_RADIOS:
        return
    field.widget = forms.RadioSelect(attrs=dict(field.widget.attrs))
    field.widget.choices = choices


def parent_of(name: str) -> str | None:
    if name.startswith("anonymous_label_"):  # the text for a participant without a nickname
        return "scoreboard_unnamed"
    return CHILD_OF.get(name)


def _ordered(group: FieldGroup) -> None:
    """Alphabetical by the label in the current language; a dependant follows its parent."""
    names = {bound.name for bound in group.fields}
    under: dict[str, list[forms.BoundField]] = {}
    tops = []
    for bound in group.fields:
        parent = parent_of(bound.name)
        if parent is not None and parent in names:
            under.setdefault(parent, []).append(bound)
            group.children.add(bound.name)
        else:
            tops.append(bound)

    def by_label(bound: forms.BoundField) -> str:
        label = COLUMNS_LEGEND if bound.name in COLUMNS else bound.label
        return bank_folders.fold(str(label))

    ordered: list[forms.BoundField] = []

    def place(bound: forms.BoundField) -> None:
        ordered.append(bound)
        children = under.get(bound.name, [])
        for child in children if bound.name in KEEP_ORDER_UNDER else sorted(children, key=by_label):
            place(child)

    for top in sorted(tops, key=by_label):
        place(top)
    group.fields = ordered


def _matches(bound: forms.BoundField, wanted: str) -> bool:
    """The label, the help and the labels of the values, in the current language."""
    texts = [str(bound.label), str(bound.help_text or "")]
    if isinstance(bound.field, forms.ChoiceField):
        texts += [str(label) for _value, label in bound.field.choices]
    return any(wanted in bank_folders.fold(text) for text in texts)


def group_fields(
    form: forms.Form,
    *,
    basic: bool,
    differs: Callable[[str], bool],
    extra: Mapping[str, tuple[str, str]] | None = None,
    skip: tuple[str, ...] = (),
    sort: bool = True,
    query: str = "",
) -> list[FieldGroup]:
    """The form's settings in the global group order; other fields are left to the page.

    `extra` places a field that is not a catalogue setting as (group, level). A field is shown
    when the view is All, when it is basic, when its value differs, or when it was refused.
    A search (`query`) shows every field and marks those that do not match: they are drawn
    `hidden`, never left out, so a save keeps their values and the quiz's overrides (AC-168).
    """
    wanted = bank_folders.fold(query.strip())
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
        _as_radios(bound.field)
        if bound.name in COLUMNS:
            group.columns[bound.name] = str(COLUMN_LABELS[bound.name])
        # a value just sent and refused with the form stays shown, even if not stored yet
        sent = form.is_bound and bound.name in form.data and bound.name in form.changed_data
        changed = differs(bound.name) or sent
        if bound.errors or changed:
            group.open = True
        if wanted:
            group.fields.append(bound)
            if not bound.errors and not _matches(bound, wanted):
                group.unmatched.add(bound.name)
        elif not basic or place[1] == BASIC or changed or bound.errors:
            group.fields.append(bound)
        else:
            group.hidden += 1
    shown = [group for group in groups.values() if group.fields or group.hidden]
    if wanted:  # without a search every group is shown, also one with only hidden fields
        for group in shown:
            group.matched = len(group.unmatched) < len(group.fields)
    if sort:  # groups and settings alphabetical by their label in the admin's language
        shown.sort(key=lambda group: bank_folders.fold(group.label))
        for group in shown:
            _ordered(group)
    return shown


def outside_groups(
    form: forms.Form, *, extra: Mapping[str, tuple[str, str]] | None = None
) -> list[forms.BoundField]:
    """Fields that are not settings, such as a quiz's address, which the page shows first."""
    return [
        bound
        for bound in form
        if bound.name not in settings.CATALOGUE and bound.name not in (extra or {})
    ]


COLOUR_PLACES = {name: ("look", BASIC) for name in ("main", "accent")}
BRANDING_PLACES = {
    f"{field}_{code}": ("look", BASIC if field == "name" else "advanced")
    for field in branding.TEXT_LIMITS
    for code in branding.LOCALES
} | {
    "contact_email": ("look", "advanced"),
    "logo": ("look", BASIC),
    "logo_source": ("look", BASIC),
    "remove_logo": ("look", BASIC),
    "hero_logo": ("look", BASIC),
    "hero_logo_source": ("look", BASIC),
    "remove_hero_logo": ("look", BASIC),
}


def colours_differ(quiz: Quiz | None) -> Callable[[str], bool]:
    """For `group_fields`: the custom colours are set at that level."""
    return lambda key: key in COLOUR_PLACES and branding.colours_of(quiz) is not None


def branding_group(form: forms.Form, request: HttpRequest, quiz: Quiz | None) -> FieldGroup | None:
    """The branding form's fields as one group, with the Basic / All rule of the settings."""
    stored = branding.texts_of(quiz)

    def differs(name: str) -> bool:
        if name == "contact_email":
            field = "contact_email"
        elif name in ("logo", "logo_source", "remove_logo"):
            field = "logo"
        elif name in ("hero_logo", "hero_logo_source", "remove_hero_logo"):
            field = "hero_logo"
        else:
            field = name.split("_")[0]
        if field == "logo":
            return branding.has_logo(quiz)
        if field == "hero_logo":
            return branding.has_hero_logo(quiz)
        return bool(stored.get(field))

    groups = group_fields(
        form, basic=is_basic(request), differs=differs, extra=BRANDING_PLACES, sort=False
    )
    return groups[0] if groups else None


def adjusted_colours(quiz: Quiz | None, locale: str) -> DerivedPalette | None:
    """The colours in use at that level when they were changed to reach WCAG AA contrast."""
    resolved = branding.resolve(quiz, locale)
    own = quiz is None or resolved.sources["colours"] == "quiz"
    if own and resolved.custom is not None and resolved.custom.adjusted:
        return resolved.custom
    return None

"""Reward forms: the name edited on the spot and one reward rule."""

from collections.abc import Mapping, Sequence
from typing import Any, cast

from django import forms
from django.utils.text import format_lazy
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from app.api.admin_forms_branding import (
    ADDRESS_HELP as ADDRESS_HELP,
)
from app.api.admin_forms_branding import (
    BRANDING_LABELS as BRANDING_LABELS,
)
from app.api.admin_forms_branding import (
    COLOUR_NAMES as COLOUR_NAMES,
)
from app.api.admin_forms_branding import (
    BrandingForm as BrandingForm,
)
from app.api.admin_forms_branding import (
    ColourInput as ColourInput,
)
from app.domain import (
    rewards,
)
from app.domain.models import RewardRule
from app.kernel import registry


class RewardNameForm(forms.Form):
    """The name of a reward in the quiz's default language, edited on the spot."""

    name = forms.CharField(label=gettext_lazy("Name"), max_length=80)


_STRUCTURE_FIELDS = (
    "kind",
    "threshold_unit",
    "threshold_value",
    "min_unit",
    "min_value",
    "winners",
    "alternates",
)


# Where a refusal of the domain belongs: (field of a threshold, field of a draw)
_RULE_ERROR_FIELDS = {
    "kind_invalid": ("kind", "kind"),
    "unit_invalid": ("threshold_unit", "min_unit"),
    "value_invalid": ("threshold_value", "min_value"),
    "value_not_positive": ("threshold_value", "min_value"),
    "percent_over_100": ("threshold_value", "min_value"),
    "winners_invalid": ("winners", "winners"),
    "alternates_invalid": ("alternates", "alternates"),
}


def rule_refusal(code: str) -> str:
    """The message for a `rewards.RuleInvalid` code."""
    messages = {
        "kind_invalid": _("Choose a kind of reward."),
        "unit_invalid": _("Choose a unit and enter a value."),
        "value_invalid": _("Enter a valid number. Correct answers are a whole number."),
        "value_not_positive": _("Enter a number greater than 0."),
        "percent_over_100": _("A percentage can be at most 100."),
        "winners_invalid": _("Enter from 1 to %(max)s winners.") % {"max": rewards.MAX_WINNERS},
        "alternates_invalid": _("Enter from 0 to %(max)s alternates.")
        % {"max": rewards.MAX_ALTERNATES},
        "text_too_long": _("A text is too long."),
        "plugin_disabled": _("The module this reward needs is disabled."),
    }
    return messages.get(code, _("This reward cannot be saved."))


class RewardRuleForm(forms.Form):
    """One reward rule. The first locale is the quiz's default, where the name is required.

    With `structure_locked` the structure fields are disabled: Django then ignores what was posted
    for them and keeps the initial values, so only the texts can change.
    """

    kind = forms.ChoiceField(
        label=gettext_lazy("Kind"),
        choices=[
            (RewardRule.Kind.THRESHOLD, gettext_lazy("Threshold: for a score that reaches it")),
            (RewardRule.Kind.PARTICIPATION, gettext_lazy("Participation: for every submission")),
            (RewardRule.Kind.MANUAL, gettext_lazy("Manual: granted by an admin")),
            (RewardRule.Kind.DRAW, gettext_lazy("Draw: winners drawn after the run")),
        ],
    )
    threshold_unit = forms.ChoiceField(
        label=gettext_lazy("Threshold unit"),
        required=False,
        choices=[
            ("", "—"),
            (RewardRule.Unit.PERCENT, gettext_lazy("Percent")),
            (RewardRule.Unit.POINTS, gettext_lazy("Points")),
            (RewardRule.Unit.CORRECT, gettext_lazy("Correct answers")),
        ],
        help_text=gettext_lazy("Only for a threshold. Reached means at least this value."),
    )
    threshold_value = forms.DecimalField(
        label=gettext_lazy("Threshold value"),
        required=False,
        max_digits=12,
        decimal_places=4,
    )
    min_unit = forms.ChoiceField(
        label=gettext_lazy("Who may be drawn"),
        required=False,
        choices=[
            ("", gettext_lazy("Everyone with a submitted attempt")),
            (RewardRule.Unit.PERCENT, gettext_lazy("At least a percentage")),
            (RewardRule.Unit.POINTS, gettext_lazy("At least a number of points")),
        ],
        help_text=gettext_lazy("Only for a draw."),
    )
    min_value = forms.DecimalField(
        label=gettext_lazy("Minimum for the draw"),
        required=False,
        max_digits=12,
        decimal_places=4,
    )
    winners = forms.IntegerField(
        label=gettext_lazy("Winners"), required=False, min_value=1, max_value=rewards.MAX_WINNERS
    )
    alternates = forms.IntegerField(
        label=gettext_lazy("Alternates"),
        required=False,
        min_value=0,
        max_value=rewards.MAX_ALTERNATES,
        initial=rewards.DEFAULT_ALTERNATES,
        help_text=format_lazy(
            gettext_lazy("Drawn after the winners, in order. Empty means {default}."),
            default=rewards.DEFAULT_ALTERNATES,
        ),
    )

    def _hide_kinds_of_disabled_plugins(self) -> None:
        """A rule being edited keeps its own kind, so that its page still opens."""
        hidden = set()
        if "threshold" not in registry.keys("reward"):
            hidden.add(RewardRule.Kind.THRESHOLD)
        if "manual" not in registry.keys("drawing"):
            hidden.add(RewardRule.Kind.DRAW)
        hidden.discard(self.initial.get("kind"))
        field = cast(forms.ChoiceField, self.fields["kind"])
        field.choices = [choice for choice in field.choices if choice[0] not in hidden]

    def __init__(
        self,
        *args: Any,
        locales: Sequence[str],
        structure_locked: bool,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.locales = list(locales)
        self.structure_locked = structure_locked
        self._hide_kinds_of_disabled_plugins()
        for number, locale in enumerate(self.locales):
            self.fields[f"name_{locale}"] = forms.CharField(
                label=_("Name (%(locale)s)") % {"locale": locale},
                max_length=80,
                required=number == 0,
            )
            self.fields[f"description_{locale}"] = forms.CharField(
                label=_("Description (%(locale)s)") % {"locale": locale},
                max_length=500,
                required=False,
                widget=forms.Textarea(attrs={"rows": 2}),
            )
            self.fields[f"claim_{locale}"] = forms.CharField(
                label=_("How to claim it (%(locale)s)") % {"locale": locale},
                max_length=500,
                required=False,
                widget=forms.Textarea(attrs={"rows": 2}),
            )
        if structure_locked:
            for name in _STRUCTURE_FIELDS:
                self.fields[name].disabled = True

    @staticmethod
    def initial_of(rule: RewardRule) -> dict[str, Any]:
        found: dict[str, Any] = {name: getattr(rule, name) for name in _STRUCTURE_FIELDS}
        for name in ("threshold_value", "min_value"):
            if found[name] is not None:
                found[name] = found[name].normalize()
        for locale, values in (rule.texts_json or {}).items():
            for name in rewards.TEXT_FIELDS:
                found[f"{name}_{locale}"] = values.get(name, "")
        return found

    def structure_fields(self) -> list[forms.BoundField]:
        return [self[name] for name in _STRUCTURE_FIELDS]

    def text_fields(self) -> list[forms.BoundField]:
        return [self[f"{name}_{locale}"] for locale in self.locales for name in rewards.TEXT_FIELDS]

    def texts(self) -> dict[str, dict[str, str]]:
        """Texts of the quiz's languages; others the rule may hold are kept by the caller."""
        return {
            locale: {name: self.cleaned_data[f"{name}_{locale}"] for name in rewards.TEXT_FIELDS}
            for locale in self.locales
        }

    def rule_data(self, texts: Mapping[str, Mapping[str, str]]) -> rewards.RuleData:
        found = self.cleaned_data
        return rewards.RuleData(
            kind=found["kind"],
            threshold_unit=found["threshold_unit"] or None,
            threshold_value=found["threshold_value"],
            min_unit=found["min_unit"] or None,
            min_value=found["min_value"],
            winners=found["winners"],
            alternates=found["alternates"],
            texts=texts,
        )

    def refuse(self, code: str) -> None:
        """Puts a `rewards.RuleInvalid` refusal next to the field it is about."""
        fields = _RULE_ERROR_FIELDS.get(code)
        field = None
        if fields is not None:
            field = (
                fields[1] if self.cleaned_data.get("kind") == RewardRule.Kind.DRAW else fields[0]
            )
        self.add_error(field, rule_refusal(code))

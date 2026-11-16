"""Quiz forms and the settings forms, with the helpers they share (clashes, numbers, labels)."""

from collections.abc import Mapping, Sequence
from typing import Any

from django import forms
from django.conf import settings as django_settings
from django.utils.text import slugify
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
from app.api.admin_forms_branding import (
    _add_colour_fields,
    _clean_colours,
    _save_colours,
)
from app.api.admin_forms_rewards import (
    RewardNameForm as RewardNameForm,
)
from app.api.admin_forms_rewards import (
    RewardRuleForm as RewardRuleForm,
)
from app.api.admin_forms_rewards import (
    rule_refusal as rule_refusal,
)
from app.api.i18n import PUBLIC_LOCALES
from app.contracts import (
    AFTER_PASS,
    COLOR_PALETTE,
    MAX_ATTEMPTS,
    PASS_MARK,
    SCOREBOARD_UNNAMED,
)
from app.domain import (
    data_policy,
    quiz_types,
    results,
    rewards,
    setting_rules,
    settings,
)
from app.domain.models import Quiz, QuizRevision

_LANGUAGE_NAMES = dict(django_settings.LANGUAGES)


LOCALE_CHOICES = [(code, _LANGUAGE_NAMES[code]) for code in PUBLIC_LOCALES]


def _slug_is_free(slug: str, quiz: Quiz | None) -> str:
    others = Quiz.objects.filter(slug=slug)
    if quiz is not None:
        others = others.exclude(pk=quiz.pk)
    if others.exists():
        raise forms.ValidationError(_("Another quiz already uses this identifier."))
    return slug


def free_slug(base: str, suffix: str = "") -> str:
    """`base` plus `suffix`, with -2, -3 ... until no quiz uses it; at most 80 characters."""
    candidate = f"{base[: 80 - len(suffix)]}{suffix}"
    number = 2
    while Quiz.objects.filter(slug=candidate).exists():
        tail = f"{suffix}-{number}"
        candidate = f"{base[: 80 - len(tail)]}{tail}"
        number += 1
    return candidate


class QuizContentForm(forms.Form):
    """What participants see after publication."""

    supported_locales = forms.MultipleChoiceField(
        label=gettext_lazy("Languages"),
        choices=LOCALE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    default_locale = forms.ChoiceField(
        label=gettext_lazy("Default language"), choices=LOCALE_CHOICES
    )

    def __init__(self, *args: Any, quiz: Quiz | None = None, **kwargs: Any) -> None:
        self.quiz = quiz
        if quiz is not None:
            kwargs.setdefault(
                "initial",
                {
                    "supported_locales": quiz.supported_locales,
                    "default_locale": quiz.default_locale,
                    **{f"title_{code}": text for code, text in quiz.title.items()},
                    **{f"description_{code}": text for code, text in quiz.description.items()},
                },
            )
        super().__init__(*args, **kwargs)
        for code in PUBLIC_LOCALES:
            self.fields[f"title_{code}"] = forms.CharField(
                label=f"{_('Title')} ({code})", max_length=200, required=False
            )
            self.fields[f"description_{code}"] = forms.CharField(
                label=f"{_('Description')} ({code})",
                max_length=300,
                required=False,
                widget=forms.Textarea(attrs={"rows": 2}),
            )

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean() or {}
        locales = cleaned.get("supported_locales")
        default = cleaned.get("default_locale")
        if locales and default and default not in locales:
            self.add_error(
                "default_locale", _("The default language must be among the selected languages.")
            )
        return cleaned

    def apply_to(self, quiz: Quiz) -> Quiz:
        data = self.cleaned_data
        quiz.supported_locales = data["supported_locales"]
        quiz.default_locale = data["default_locale"]
        quiz.title = {
            code: data[f"title_{code}"] for code in PUBLIC_LOCALES if data[f"title_{code}"]
        }
        quiz.description = {
            code: data[f"description_{code}"]
            for code in PUBLIC_LOCALES
            if data[f"description_{code}"]
        }
        quiz.save()
        return quiz


class QuizNameForm(forms.Form):
    """The title in the default language, edited on the spot."""

    name = forms.CharField(label=gettext_lazy("Title"), max_length=200)


class QuizForm(QuizContentForm):
    """A new quiz, with everything at once."""

    slug = forms.SlugField(
        label=gettext_lazy("URL identifier"),
        max_length=80,
        required=False,
        help_text=gettext_lazy("Leave empty to derive it from the name"),
    )
    featured = forms.BooleanField(label=gettext_lazy("Highlight on the home page"), required=False)
    field_order = ("slug", "supported_locales", "default_locale", "featured")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        default = django_settings.LANGUAGE_CODE
        kwargs.setdefault("initial", {"supported_locales": [default], "default_locale": default})
        super().__init__(*args, **kwargs)
        offered = quiz_types.available()
        self.type_descriptions = {item.id: item.description() for item in offered}
        if offered:  # without the types module the quiz is created as before
            self.fields["quiz_type"] = forms.ChoiceField(
                label=_("Quiz type"),
                choices=[("", _("No type")), *((item.id, item.label()) for item in offered)],
                initial="",
                required=False,
                widget=forms.RadioSelect,
            )

    def chosen_type(self) -> str:
        return str(self.cleaned_data.get("quiz_type") or "")

    def clean_slug(self) -> str:
        slug = self.cleaned_data["slug"]
        return _slug_is_free(slug, self.quiz) if slug else ""

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean() or {}
        if cleaned.get("slug") or "slug" in self.errors:
            return cleaned
        default = cleaned.get("default_locale") or django_settings.LANGUAGE_CODE
        title = (cleaned.get(f"title_{default}") or "").strip()
        derived = slugify(title)[:80].strip("-")
        if not title:
            self.add_error(
                f"title_{default}", _("Enter the title, or the URL identifier to use instead.")
            )
        elif not derived:
            self.add_error(
                "slug",
                _("This name cannot be turned into an address. Fill in the URL identifier."),
            )
        else:
            cleaned["slug"] = free_slug(derived)
        return cleaned

    def apply_to(self, quiz: Quiz) -> Quiz:
        quiz.slug = self.cleaned_data["slug"]
        quiz.featured = self.cleaned_data["featured"]
        return super().apply_to(quiz)


class DuplicateQuizForm(forms.Form):
    slug = forms.SlugField(label=gettext_lazy("URL identifier"), max_length=80)

    def clean_slug(self) -> str:
        slug = self.cleaned_data["slug"]
        if Quiz.objects.filter(slug=slug).exists():
            raise forms.ValidationError(_("Another quiz already uses this identifier."))
        return slug


def conflict_messages(keys: Sequence[str]) -> list[str]:
    """One line per setting that the profile "nothing" cannot go with, naming that setting."""
    lines = []
    for key in keys:
        if key == data_policy.PHOTO_QUESTION:
            lines.append(
                _("Nothing is kept, so the quiz cannot have a photo question: a photo is stored.")
            )
            continue
        if key == settings.REVEAL_MOMENT:
            lines.append(
                _("Answers shown after the run closes need the data profile Answers or Detailed.")
            )
            continue
        if key == MAX_ATTEMPTS:
            lines.append(_("Nothing is kept, which does not go with a limit on attempts."))
            continue
        if key == AFTER_PASS:
            lines.append(
                _("Nothing is kept, which does not go with stopping attempts after passing.")
            )
            continue
        name = settings.CATALOGUE[key].label
        lines.append(
            _('Nothing is kept, which does not go with the setting "%(name)s" as it is.')
            % {"name": name}
        )
    return lines


def result_messages(reasons: Sequence[str]) -> list[str]:
    """One line per reason a scoreboard setting was refused."""
    texts = {
        results.STATELESS: _("Nothing is kept, so the run cannot have a public scoreboard."),
        results.AFTER_EACH: _("Answers after each question cannot go with a visible scoreboard."),
        results.NEEDS_TIMES: _("The duration needs the data profile that keeps times."),
        results.TEST_RUN: _("A test run has no scoreboard."),
    }
    return [str(texts[reason]) for reason in reasons]


def _clash_messages() -> dict[str, str]:
    return {
        setting_rules.FLOW: _("Answers after each question need a one-by-one mode."),
        setting_rules.VISIBILITY: _(
            "Showing answers to anyone but admins needs a profile that keeps all answers."
        ),
        setting_rules.AFTER_CLOSE_PROFILE: _(
            "Answers shown after the run closes need the data profile Answers or Detailed."
        ),
        setting_rules.AFTER_CLOSE_VISIBILITY: _(
            "Answers shown after the run closes need participants to see their answers."
        ),
        setting_rules.RUN_PROFILE: _(
            "A planned or open run keeps no answers, so it cannot show them after it closes."
        ),
        setting_rules.RUN_BOARD: result_messages([results.AFTER_EACH])[0],
        setting_rules.RUN_REWARDS: str(rewards.messages([rewards.REVEAL])[0]),
    }


def clash_message(clash: setting_rules.Clash) -> str:
    """What the settings forms say about a clash; a quiz type refused by one says the same."""
    if clash.reason == setting_rules.STATELESS:
        return conflict_messages([str(clash.detail)])[0]
    texts = _clash_messages()
    if clash.reason in texts:
        return texts[clash.reason]
    return result_messages([clash.reason])[0]


def _refuse_clashes(form: forms.Form, quiz: Quiz | None) -> None:
    """Empty fields mean the global value, in both forms. The rules are in the domain (AC-18)."""
    values = {
        key: value for key, value in form.cleaned_data.items() if isinstance(value, str) and value
    }
    for clash in setting_rules.clashes(values, quiz):
        form.add_error(clash.key if clash.key in form.fields else None, clash_message(clash))


def setting_label(key: str) -> str:
    """A key a release no longer knows is shown as it is."""
    definition = settings.CATALOGUE.get(key)
    return str(definition.label) if definition else key


def setting_value_label(key: str, value: str) -> str:
    """A value as the settings form names it; a time limit with its unit."""
    definition = settings.CATALOGUE.get(key)
    if definition is None:
        return value
    unit = NUMBER_KEYS.get(key)
    if unit and value != "0" and value.isdigit():
        if unit == "min":
            return _("%(minutes)s min") % {"minutes": value}
        return f"{value} {unit}".strip()
    return str(definition.value_labels.get(value, value))


def _value_choices(key: str) -> list[tuple[str, Any]]:
    definition = settings.CATALOGUE[key]
    return [(value, definition.value_labels[value]) for value in definition.choices]


# Settings whose choices are the numbers 0 to N: key -> the unit shown after a value.
NUMBER_KEYS: Mapping[str, str] = {
    settings.ATTEMPT_LIMIT: "min",
    PASS_MARK: "%",
    MAX_ATTEMPTS: "",
}


# A number field's help where the catalogue has none that fits a number box.
_NUMBER_HELP: Mapping[str, Any] = {
    settings.ATTEMPT_LIMIT: gettext_lazy("In minutes. 0 means no limit."),
}


class NumberChoiceField(forms.IntegerField):
    """A number kept as the string the settings catalogue stores; empty follows the level above."""

    def __init__(self, key: str, **kwargs: Any) -> None:
        kwargs.setdefault("min_value", 0)
        kwargs.setdefault("max_value", int(settings.CATALOGUE[key].choices[-1]))
        super().__init__(**kwargs)

    def clean(self, value: Any) -> str:
        number = super().clean(value)
        return "" if number is None else str(number)


def _number_help(key: str) -> str:
    return str(_NUMBER_HELP.get(key) or settings.CATALOGUE[key].help or "")


class GlobalSettingsForm(forms.Form):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for key in settings.keys_for("global"):
            definition = settings.CATALOGUE[key]
            if key in NUMBER_KEYS:
                self.fields[key] = NumberChoiceField(
                    key,
                    label=definition.label,
                    help_text=_number_help(key),
                    initial=settings.resolve(key),
                    required=False,
                )
                continue
            self.fields[key] = forms.ChoiceField(
                label=definition.label,
                help_text=definition.help or "",
                choices=_value_choices(key),
                initial=settings.resolve(key),
                required=False,
            )
        _add_colour_fields(self, None)

    def palette(self) -> str:
        return str(self.cleaned_data.get(COLOR_PALETTE) or settings.resolve(COLOR_PALETTE))

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        _refuse_clashes(self, getattr(self, "quiz", None))
        _clean_colours(self, self.palette())
        return cleaned

    def save_colours(self, admin_id: str) -> None:
        _save_colours(self, self.palette(), None, admin_id)


class QuizBehaviourForm(forms.Form):
    """What applies as soon as it is saved. An empty setting follows the global value."""

    slug = forms.SlugField(
        label=gettext_lazy("URL identifier"),
        max_length=80,
        help_text=gettext_lazy(
            "Locked after the first publication, so that printed QR codes work."
        ),
    )
    featured = forms.BooleanField(label=gettext_lazy("Highlight on the home page"), required=False)

    def __init__(self, *args: Any, quiz: Quiz, **kwargs: Any) -> None:
        self.quiz = quiz
        kwargs.setdefault("initial", {"slug": quiz.slug, "featured": quiz.featured})
        super().__init__(*args, **kwargs)
        if quiz.revisions.exclude(status=QuizRevision.Status.DRAFT).exists():
            self.fields["slug"].disabled = True
        for key in settings.keys_for("quiz"):
            definition = settings.CATALOGUE[key]
            current = setting_value_label(key, settings.resolve(key))
            inherit = _("Use global setting (now: %(value)s)") % {"value": current}
            if key in NUMBER_KEYS:
                self.fields[key] = NumberChoiceField(
                    key,
                    label=definition.label,
                    help_text=f"{_number_help(key)} {_('Empty:')} {inherit}",
                    initial=settings.quiz_override(key, quiz) or "",
                    required=False,
                )
                continue
            self.fields[key] = forms.ChoiceField(
                label=definition.label,
                help_text=definition.help or "",
                choices=[("", inherit), *_value_choices(key)],
                initial=settings.quiz_override(key, quiz) or "",
                required=False,
            )
            if key == SCOREBOARD_UNNAMED:
                self._add_labels(quiz)
        _add_colour_fields(self, quiz)

    def palette(self) -> str:
        return str(self.cleaned_data.get(COLOR_PALETTE) or "")  # empty follows the global one

    def save_colours(self, admin_id: str) -> None:
        _save_colours(self, self.palette(), self.quiz, admin_id)

    def _add_labels(self, quiz: Quiz) -> None:
        """Free text per language, so a quiz field beside the scoreboard settings (ADR-0051)."""
        for code in quiz.supported_locales:
            self.fields[f"anonymous_label_{code}"] = forms.CharField(
                label=f"{_('Anonymous participant on the scoreboard')} ({code})",
                max_length=results.MAX_LABEL,
                required=False,
                initial=quiz.anonymous_label.get(code, ""),
                help_text=_('NN stands for the number. Empty uses "Player NN" in that language.'),
            )

    def clean_slug(self) -> str:
        return _slug_is_free(self.cleaned_data["slug"], self.quiz)

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        _refuse_clashes(self, getattr(self, "quiz", None))
        _clean_colours(self, self.palette())
        return cleaned

    def apply_to(self, quiz: Quiz) -> None:
        quiz.slug = self.cleaned_data["slug"]
        quiz.featured = self.cleaned_data["featured"]
        shown = [code for code in PUBLIC_LOCALES if f"anonymous_label_{code}" in self.fields]
        if shown:  # none without the results module; a language the quiz dropped keeps its text
            kept = {k: v for k, v in quiz.anonymous_label.items() if k not in shown}
            typed = {code: self.cleaned_data[f"anonymous_label_{code}"].strip() for code in shown}
            quiz.anonymous_label = kept | {code: text for code, text in typed.items() if text}
        quiz.save()

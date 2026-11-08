"""Admin forms. Question forms are not here: each question type reads its own (`parse_admin`)."""

from collections.abc import Mapping, Sequence
from typing import Any

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.utils.text import format_lazy
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from app.api.i18n import PUBLIC_LOCALES
from app.contracts import (
    PARTICIPANT_KEYS,
    RESULT_KEYS,
    REWARD_RUN_KEYS,
    SCOREBOARD_UNNAMED,
    SCOREBOARD_VISIBILITY,
    QuestionTypePlugin,
)
from app.domain import access_codes, clock, data_policy, questions, results, rewards, settings
from app.domain.models import Quiz, QuizRevision, QuizRun, RewardRule

LOCALE_CHOICES = [(code, code) for code in PUBLIC_LOCALES]


class LoginForm(forms.Form):
    login = forms.CharField(label=gettext_lazy("Login"), max_length=150)
    password = forms.CharField(
        label=gettext_lazy("Password"), strip=False, widget=forms.PasswordInput
    )


def _slug_is_free(slug: str, quiz: Quiz | None) -> str:
    others = Quiz.objects.filter(slug=slug)
    if quiz is not None:
        others = others.exclude(pk=quiz.pk)
    if others.exists():
        raise forms.ValidationError(_("Another quiz already uses this identifier."))
    return slug


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


class QuizForm(QuizContentForm):
    """A new quiz, with everything at once."""

    slug = forms.SlugField(label=gettext_lazy("URL identifier"), max_length=80)
    featured = forms.BooleanField(label=gettext_lazy("Highlight on the home page"), required=False)
    field_order = ("slug", "supported_locales", "default_locale", "featured")

    def clean_slug(self) -> str:
        return _slug_is_free(self.cleaned_data["slug"], self.quiz)

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


MAX_EXPLANATION_LENGTH = 2000
MAX_TAGS = 10
MAX_TAG_LENGTH = 40


def _refuse_flow_conflict(form: forms.Form) -> None:
    """Empty fields mean the global value, in both forms."""
    navigation = form.cleaned_data.get(settings.NAVIGATION_MODE) or settings.resolve(
        settings.NAVIGATION_MODE
    )
    moment = form.cleaned_data.get(settings.REVEAL_MOMENT) or settings.resolve(
        settings.REVEAL_MOMENT
    )
    if settings.is_flow_conflict(navigation, moment):
        form.add_error(
            settings.REVEAL_MOMENT,
            _("Answers after each question need a one-by-one mode."),
        )


def _refuse_visibility_conflict(form: forms.Form) -> None:
    profile = form.cleaned_data.get(settings.DATA_PROFILE) or settings.resolve(
        settings.DATA_PROFILE
    )
    visibility = form.cleaned_data.get(settings.ANSWERS_VISIBILITY) or settings.resolve(
        settings.ANSWERS_VISIBILITY
    )
    if settings.is_visibility_conflict(profile, visibility):
        form.add_error(
            settings.ANSWERS_VISIBILITY,
            _("Showing answers to anyone but admins needs a profile that keeps all answers."),
        )


def conflict_messages(keys: Sequence[str]) -> list[str]:
    """One line per setting that the profile "nothing" cannot go with, naming that setting."""
    lines = []
    for key in keys:
        if key == data_policy.PHOTO_QUESTION:
            lines.append(
                _("Nothing is kept, so the quiz cannot have a photo question: a photo is stored.")
            )
            continue
        name = settings.CATALOGUE[key].label
        lines.append(
            _('Nothing is kept, which does not go with the setting "%(name)s" as it is.')
            % {"name": name}
        )
    return lines


def _refuse_stateless_conflict(form: forms.Form) -> None:
    """Under "nothing" no one is remembered, so the rules about people must stay off."""
    profile = form.cleaned_data.get(settings.DATA_PROFILE) or settings.resolve(
        settings.DATA_PROFILE
    )
    rules = {key: form.cleaned_data.get(key) or settings.resolve(key) for key in PARTICIPANT_KEYS}
    # The visibility conflict has its own message above.
    keys = data_policy.conflicts(profile, rules, settings.AnswersVisibility.ADMINS.value, None)
    for key, message in zip(keys, conflict_messages(keys), strict=True):
        form.add_error(key if key in form.fields else None, message)


def result_messages(reasons: Sequence[str]) -> list[str]:
    """One line per reason a scoreboard setting was refused."""
    texts = {
        results.STATELESS: _("Nothing is kept, so the run cannot have a public scoreboard."),
        results.AFTER_EACH: _("Answers after each question cannot go with a visible scoreboard."),
        results.NEEDS_TIMES: _("The duration needs the data profile that keeps times."),
        results.TEST_RUN: _("A test run has no scoreboard."),
    }
    return [str(texts[reason]) for reason in reasons]


def _visible_board_on_a_run(quiz: Quiz | None) -> bool:
    """For the global form, the runs of every quiz that takes the global answers setting."""
    live = (QuizRun.Status.SCHEDULED, QuizRun.Status.OPEN)
    if quiz is not None:
        return any(results.needs_participant(run) for run in quiz.runs.filter(status__in=live))
    return any(
        results.needs_participant(run)
        for run in QuizRun.objects.filter(status__in=live).select_related("quiz")
        if settings.quiz_override(settings.REVEAL_MOMENT, run.quiz) is None
    )


def _refuse_result_conflict(form: forms.Form, quiz: Quiz | None = None) -> None:
    """Empty fields mean the global value. Runs already planned or open count too (AC-18)."""
    chosen = {key: form.cleaned_data.get(key) or settings.resolve(key) for key in RESULT_KEYS}
    profile = form.cleaned_data.get(settings.DATA_PROFILE) or settings.resolve(
        settings.DATA_PROFILE
    )
    moment = form.cleaned_data.get(settings.REVEAL_MOMENT) or settings.resolve(
        settings.REVEAL_MOMENT
    )
    why = results.reasons(chosen, profile=profile, reveal_moment=moment)
    if (
        moment == settings.RevealMoment.AFTER_EACH
        and results.AFTER_EACH not in why
        and _visible_board_on_a_run(quiz)
    ):
        why.append(results.AFTER_EACH)
    fields = {
        results.STATELESS: SCOREBOARD_VISIBILITY,
        results.AFTER_EACH: settings.REVEAL_MOMENT,
        results.NEEDS_TIMES: SCOREBOARD_VISIBILITY,
    }
    for reason, message in zip(why, result_messages(why), strict=True):
        field = fields[reason]
        form.add_error(field if field in form.fields else None, message)


def _rewards_on_a_run(quiz: Quiz | None) -> bool:
    """Like `_visible_board_on_a_run`, for runs planned or open with reward rules."""
    live = (QuizRun.Status.SCHEDULED, QuizRun.Status.OPEN)
    if quiz is not None:
        return any(rewards.has_rules(run) for run in quiz.runs.filter(status__in=live))
    return any(
        rewards.has_rules(run)
        for run in QuizRun.objects.filter(status__in=live).select_related("quiz")
        if settings.quiz_override(settings.REVEAL_MOMENT, run.quiz) is None
    )


def _refuse_reward_conflict(form: forms.Form, quiz: Quiz | None = None) -> None:
    """Answers after each question would tell a player what the next attempt needs (AC-18)."""
    moment = form.cleaned_data.get(settings.REVEAL_MOMENT) or settings.resolve(
        settings.REVEAL_MOMENT
    )
    if moment == settings.RevealMoment.AFTER_EACH and _rewards_on_a_run(quiz):
        field = settings.REVEAL_MOMENT
        form.add_error(
            field if field in form.fields else None, rewards.messages([rewards.REVEAL])[0]
        )


def _value_choices(key: str) -> list[tuple[str, Any]]:
    definition = settings.CATALOGUE[key]
    return [(value, definition.value_labels[value]) for value in definition.choices]


class _MinutesField(forms.IntegerField):
    """A limit in minutes, kept as the string the settings catalogue stores. 0 means no limit."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("min_value", 0)
        kwargs.setdefault("max_value", settings.MAX_LIMIT_MINUTES)
        super().__init__(**kwargs)

    def clean(self, value: Any) -> str:
        number = super().clean(value)
        return "" if number is None else str(number)


def _limit_help() -> str:
    return _("In minutes. 0 means no limit.")


class GlobalSettingsForm(forms.Form):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for key in settings.keys_for("global"):
            definition = settings.CATALOGUE[key]
            if key == settings.ATTEMPT_LIMIT:
                self.fields[key] = _MinutesField(
                    label=definition.label,
                    help_text=_limit_help(),
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

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        _refuse_flow_conflict(self)
        _refuse_visibility_conflict(self)
        _refuse_stateless_conflict(self)
        _refuse_result_conflict(self, getattr(self, "quiz", None))
        _refuse_reward_conflict(self, getattr(self, "quiz", None))
        return cleaned


class _LocalTimeField(forms.CharField):
    """A `datetime-local` field read in the configured zone."""

    widget = forms.DateTimeInput(attrs={"type": "datetime-local"})

    def clean(self, value: Any) -> Any:
        text = super().clean(value)
        if not text:
            return None
        try:
            parsed = clock.parse_local(text)
        except ValueError as exc:
            message = (
                _("This time does not exist because of the clock change.")
                if str(exc) == clock.NO_SUCH_TIME
                else _("Enter a valid time.")
            )
            raise forms.ValidationError(message) from exc
        return parsed


class RunPlanForm(forms.Form):
    starts_at = _LocalTimeField(
        label=gettext_lazy("Start time"),
        required=False,
        help_text=gettext_lazy("Empty starts the run now."),
    )
    deadline_at = _LocalTimeField(
        label=gettext_lazy("Deadline"),
        required=False,
        help_text=gettext_lazy("Empty means the run lasts until you end it."),
    )
    limit_minutes = forms.IntegerField(
        label=gettext_lazy("Time limit for an attempt (minutes)"),
        required=False,
        min_value=0,
        max_value=settings.MAX_LIMIT_MINUTES,
        help_text=gettext_lazy("Empty or 0 means no limit. It cannot change once the run opens."),
    )

    data_profile = forms.ChoiceField(
        label=settings.CATALOGUE[settings.DATA_PROFILE].label,
        choices=lambda: _value_choices(settings.DATA_PROFILE),
        required=False,
        help_text=gettext_lazy(
            "Nothing: only counts, so there is no attempts table, result link, scoreboard, "
            "draw or export. Score and photos: rankings by time need the last profile. "
            "Score and all answers: every answer is kept. "
            "Score, all answers and times: also how long each attempt took. "
            "It cannot change once the run opens."
        ),
    )
    retention_period = forms.ChoiceField(
        label=settings.CATALOGUE[settings.RETENTION_PERIOD].label,
        choices=lambda: _value_choices(settings.RETENTION_PERIOD),
        required=False,
        help_text=gettext_lazy("It can change later, also after the run ends."),
    )
    access_code = forms.CharField(
        label=gettext_lazy("Access code"),
        required=False,
        max_length=64,
        strip=True,
        help_text=gettext_lazy(
            "Optional. Participants must enter it before they start. It is shown once after saving."
        ),
    )
    generate_code = forms.BooleanField(label=gettext_lazy("Generate a code"), required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.refused: set[str] = set()  # settings a refusal names; the page shows them (ADR-0052)
        for key in (*PARTICIPANT_KEYS, *RESULT_KEYS, *REWARD_RUN_KEYS):
            definition = settings.CATALOGUE[key]
            self.fields[key] = forms.ChoiceField(
                label=definition.label,
                help_text=definition.help or "",
                choices=_value_choices(key),
                required=False,
            )

    def limit_seconds(self) -> int | None:
        return (self.cleaned_data["limit_minutes"] or 0) * 60 or None

    def code(self) -> str | None:
        """A typed code wins, else a generated one when asked. None leaves the code alone."""
        typed = self.cleaned_data["access_code"]
        if typed:
            return typed
        return access_codes.generate() if self.cleaned_data["generate_code"] else None

    def rules(self) -> dict[str, str]:
        """Only what was chosen; the rest follows the quiz."""
        return {key: self.cleaned_data[key] for key in PARTICIPANT_KEYS if self.cleaned_data[key]}

    def results(self) -> dict[str, str]:
        """Only what was chosen; the rest follows the quiz."""
        return {key: self.cleaned_data[key] for key in RESULT_KEYS if self.cleaned_data[key]}

    def rewards(self) -> dict[str, str]:
        """Only what was chosen; an empty field follows the quiz, or keeps the run's value."""
        return {key: self.cleaned_data[key] for key in REWARD_RUN_KEYS if self.cleaned_data[key]}

    def retention(self) -> dict[str, str]:
        """Only what was chosen; the rest follows the quiz."""
        chosen = {
            data_policy.PROFILE: self.cleaned_data[settings.DATA_PROFILE],
            data_policy.PERIOD: self.cleaned_data[settings.RETENTION_PERIOD],
        }
        return {key: value for key, value in chosen.items() if value}


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
            current = definition.value_labels[settings.resolve(key)]
            inherit = _("Use global setting (now: %(value)s)") % {"value": current}
            if key == settings.ATTEMPT_LIMIT:
                self.fields[key] = _MinutesField(
                    label=definition.label,
                    help_text=f"{_limit_help()} {_('Empty:')} {inherit}",
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
        _refuse_flow_conflict(self)
        _refuse_visibility_conflict(self)
        _refuse_stateless_conflict(self)
        _refuse_result_conflict(self, getattr(self, "quiz", None))
        _refuse_reward_conflict(self, getattr(self, "quiz", None))
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


def setting_initial(question: Mapping[str, Any]) -> dict[str, str]:
    """Stored question values, as a question form starts with them."""
    stored = question.get("settings", {})
    return {f"setting_{key}": stored[key] for key in settings.CATALOGUE if key in stored}


class QuestionCommonForm(forms.Form):
    """What every question type has. An empty field keeps the stored value."""

    points = forms.IntegerField(
        label=gettext_lazy("Points"), min_value=1, max_value=100, required=False
    )
    scoring = forms.ChoiceField(
        label=gettext_lazy("Scoring"),
        required=False,
        help_text=gettext_lazy(
            "Part by part: every correct answer adds its share and a wrong tick subtracts it, "
            "down to zero."
        ),
    )
    sources = forms.CharField(
        label=gettext_lazy("Sources (optional)"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=gettext_lazy(
            "One per line. An address starting with https:// becomes a link. "
            "Participants see them with the result, if the settings allow it."
        ),
    )

    def __init__(
        self,
        *args: Any,
        strategies: Sequence[tuple[str, str]],
        locales: Sequence[str],
        plugin: QuestionTypePlugin,
        quiz: Quiz | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["scoring"].choices = strategies
        self.locales = list(locales)
        self._setting_keys = [
            key
            for key in settings.keys_for("question")
            if key in settings.ALL_TYPES_QUESTION_SETTINGS or key in plugin.question_settings()
        ]
        for key in self._setting_keys:
            definition = settings.CATALOGUE[key]
            current = definition.value_labels[settings.resolve(key, quiz)]
            text = (
                _("Use quiz setting (now: %(value)s)")
                if quiz
                else _("Use global setting (now: %(value)s)")
            )
            self.fields[f"setting_{key}"] = forms.ChoiceField(
                label=definition.label,
                help_text=definition.help or "",
                choices=[("", text % {"value": current}), *_value_choices(key)],
                required=False,
            )
        for locale in self.locales:
            self.fields[f"explanation_{locale}"] = forms.CharField(
                label=_("Explanation (optional), %(language)s") % {"language": locale},
                required=False,
                max_length=MAX_EXPLANATION_LENGTH,
                widget=forms.Textarea(attrs={"rows": 3}),
                help_text=gettext_lazy(
                    "Participants see it with the correct answer, if the settings allow it."
                ),
            )

    def setting_values(self) -> dict[str, str]:
        """Only what was chosen, so a question follows the quiz by default."""
        values = {key: self.cleaned_data[f"setting_{key}"] for key in self._setting_keys}
        return {key: value for key, value in values.items() if value}

    def explanation(self) -> dict[str, str]:
        """Blank languages are left out, so a blank field means no explanation there."""
        texts = {
            locale: self.cleaned_data[f"explanation_{locale}"].strip() for locale in self.locales
        }
        return {locale: text for locale, text in texts.items() if text}

    def clean_sources(self) -> list[str]:
        lines = [line.strip() for line in self.cleaned_data["sources"].splitlines()]
        sources = [line for line in lines if line]
        if len(sources) > questions.MAX_SOURCES:
            raise forms.ValidationError(
                _("At most %(count)s sources are allowed.") % {"count": questions.MAX_SOURCES}
            )
        if any(len(line) > questions.MAX_SOURCE_LENGTH for line in sources):
            raise forms.ValidationError(
                _("A source can have at most %(count)s characters.")
                % {"count": questions.MAX_SOURCE_LENGTH}
            )
        return sources


class BankQuestionForm(QuestionCommonForm):
    """Points belong to the draw row, so that everyone plays for the same maximum."""

    tags = forms.CharField(
        label=gettext_lazy("Tags (optional)"),
        required=False,
        help_text=gettext_lazy("Separated by commas. A quiz can draw only questions with one tag."),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        del self.fields["points"]

    def clean_tags(self) -> list[str]:
        tags = [tag.strip() for tag in self.cleaned_data["tags"].split(",") if tag.strip()]
        if len(tags) > MAX_TAGS:
            raise forms.ValidationError(
                _("At most %(count)s tags are allowed.") % {"count": MAX_TAGS}
            )
        if any(len(tag) > MAX_TAG_LENGTH for tag in tags):
            raise forms.ValidationError(
                _("A tag can have at most %(count)s characters.") % {"count": MAX_TAG_LENGTH}
            )
        return tags


class BankForm(forms.Form):
    name = forms.CharField(label=gettext_lazy("Bank name"), max_length=120)


class DrawForm(forms.Form):
    """One row "N questions from a bank" in a quiz."""

    bank = forms.ChoiceField(label=gettext_lazy("Bank"))
    tag = forms.CharField(
        label=gettext_lazy("Tag (optional)"),
        required=False,
        max_length=MAX_TAG_LENGTH,
        help_text=gettext_lazy("Without a tag, questions are drawn from the whole bank."),
    )
    count = forms.IntegerField(
        label=gettext_lazy("Number of questions"), min_value=1, max_value=100
    )
    points = forms.IntegerField(
        label=gettext_lazy("Points per question"), min_value=1, max_value=100
    )
    position = forms.TypedChoiceField(label=gettext_lazy("Position"), coerce=int)

    def __init__(
        self,
        *args: Any,
        banks: Sequence[tuple[str, str]],
        own_questions: int,
        tags: Sequence[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["bank"].choices = banks
        self.fields["position"].choices = [
            (0, _("At the start")),
            *(
                (number, _("After question %(number)s") % {"number": number})
                for number in range(1, own_questions + 1)
            ),
        ]
        self.fields["tag"].widget.attrs["list"] = "bank-tags"
        self.tag_options = list(tags)


class AdminUserForm(forms.Form):
    login = forms.CharField(label=gettext_lazy("Login"), max_length=150)
    password = forms.CharField(
        label=gettext_lazy("Password"), strip=False, widget=forms.PasswordInput
    )

    def clean_login(self) -> str:
        login = self.cleaned_data["login"]
        if get_user_model().objects.filter(login=login).exists():
            raise forms.ValidationError(_("This login already exists."))
        return login

    def clean_password(self) -> str:
        password = self.cleaned_data["password"]
        password_validation.validate_password(password)
        return password

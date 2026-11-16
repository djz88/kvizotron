"""Admin forms. Question forms are not here: each question type reads its own (`parse_admin`)."""

from collections.abc import Mapping, Sequence
from typing import Any

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from app.api.admin_forms_branding import (
    ADDRESS_HELP,
    BRANDING_LABELS,
    COLOUR_NAMES,
    BrandingForm,
    ColourInput,
)
from app.api.admin_forms_quiz import (
    LOCALE_CHOICES,
    NUMBER_KEYS,
    DuplicateQuizForm,
    GlobalSettingsForm,
    NumberChoiceField,
    QuizBehaviourForm,
    QuizContentForm,
    QuizForm,
    QuizNameForm,
    _number_help,
    _value_choices,
    clash_message,
    conflict_messages,
    free_slug,
    result_messages,
    setting_label,
    setting_value_label,
    title_taken_message,
)
from app.api.admin_forms_rewards import (
    RewardNameForm,
    RewardRuleForm,
    rule_refusal,
)
from app.contracts import (
    PARTICIPANT_KEYS,
    RESULT_KEYS,
    REWARD_RUN_KEYS,
    QuestionTypePlugin,
)
from app.domain import (
    access_codes,
    clock,
    data_policy,
    questions,
    settings,
)
from app.domain import banks as bank_levels
from app.domain.models import Quiz


class LoginForm(forms.Form):
    login = forms.CharField(label=gettext_lazy("Login"), max_length=150)
    password = forms.CharField(
        label=gettext_lazy("Password"), strip=False, widget=forms.PasswordInput
    )


MAX_EXPLANATION_LENGTH = 2000
MAX_TAGS = 10
MAX_TAG_LENGTH = 40


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
            if key in NUMBER_KEYS:
                self.fields[key] = NumberChoiceField(
                    key, label=definition.label, help_text=_number_help(key), required=False
                )
                continue
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

    folder = forms.ChoiceField(label=gettext_lazy("Folder"), required=False)
    tags = forms.CharField(
        label=gettext_lazy("Tags (optional)"),
        required=False,
        help_text=gettext_lazy(
            "Separated by commas. A quiz can draw only questions with one tag. "
            "One of easy, normal and hard sets the difficulty."
        ),
    )

    def __init__(self, *args: Any, folders: Sequence[tuple[str, str]] = (), **kwargs: Any) -> None:
        """`folders` are `(folder id, path)` of the bank; the choice must be one of them."""
        super().__init__(*args, **kwargs)
        del self.fields["points"]
        self.fields["folder"].choices = [("", _("Unfiled")), *folders]

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
        try:
            bank_levels.check_one_level(tags)
        except bank_levels.MoreThanOneLevel as exc:
            raise forms.ValidationError(
                _("A question can have only one of the tags easy, normal and hard.")
            ) from exc
        return tags


class BankForm(forms.Form):
    name = forms.CharField(label=gettext_lazy("Bank name"), max_length=120)


class DrawForm(forms.Form):
    """One row "N questions from a bank" in a quiz."""

    bank = forms.ChoiceField(label=gettext_lazy("Bank"))
    folder = forms.ChoiceField(
        label=gettext_lazy("Folder (optional)"),
        required=False,
        help_text=gettext_lazy("A folder includes its subfolders. With a tag, both must match."),
    )
    tag = forms.CharField(
        label=gettext_lazy("Tag (optional)"),
        required=False,
        max_length=MAX_TAG_LENGTH,
        help_text=gettext_lazy("Without a tag, questions are drawn from the whole bank."),
    )
    difficulty = forms.ChoiceField(
        label=gettext_lazy("Difficulty"),
        required=False,
        help_text=gettext_lazy(
            "A random mix draws every level. A question without a level counts as normal."
        ),
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
        folders: Sequence[tuple[str, str, str]] = (),
        **kwargs: Any,
    ) -> None:
        """`folders` are `(folder id, label, bank id)`; a folder must be one of the chosen bank."""
        super().__init__(*args, **kwargs)
        self.fields["bank"].choices = banks
        self.fields["folder"].choices = [
            ("", _("Whole bank")),
            *((folder_id, label) for folder_id, label, _bank in folders),
        ]
        self._folder_banks = {folder_id: bank_id for folder_id, _label, bank_id in folders}
        self.fields["position"].choices = [
            (0, _("At the start")),
            *(
                (number, _("After question %(number)s") % {"number": number})
                for number in range(1, own_questions + 1)
            ),
        ]
        self.fields["difficulty"].choices = bank_levels.level_choices()
        self.fields["tag"].widget.attrs["list"] = "bank-tags"
        self.tag_options = list(tags)

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        folder, bank = data.get("folder"), data.get("bank")
        if folder and self._folder_banks.get(folder) != bank:
            self.add_error("folder", _("Choose a folder of the chosen bank."))
        return data


EMAIL_HELP = gettext_lazy(
    "Optional. It can appear in the footers of this admin's quizzes as a contact."
)


class AdminUserForm(forms.Form):
    login = forms.CharField(label=gettext_lazy("Login"), max_length=150)
    password = forms.CharField(
        label=gettext_lazy("Password"), strip=False, widget=forms.PasswordInput
    )

    email = forms.EmailField(
        label=gettext_lazy("E-mail"),
        max_length=254,
        required=False,
        help_text=EMAIL_HELP,
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


class AdminEmailForm(forms.Form):
    """Changes the optional e-mail of one account."""

    admin_id = forms.UUIDField(widget=forms.HiddenInput)
    email = forms.EmailField(
        label=gettext_lazy("E-mail"),
        max_length=254,
        required=False,
        help_text=EMAIL_HELP,
    )


# Names that moved to the split modules and are still imported from here (not a star-import list).
__all__ = [
    "ADDRESS_HELP",
    "BRANDING_LABELS",
    "BrandingForm",
    "COLOUR_NAMES",
    "ColourInput",
    "DuplicateQuizForm",
    "GlobalSettingsForm",
    "LOCALE_CHOICES",
    "NUMBER_KEYS",
    "NumberChoiceField",
    "QuizBehaviourForm",
    "QuizContentForm",
    "QuizForm",
    "QuizNameForm",
    "RewardNameForm",
    "RewardRuleForm",
    "_number_help",
    "_value_choices",
    "clash_message",
    "conflict_messages",
    "free_slug",
    "result_messages",
    "title_taken_message",
    "rule_refusal",
    "setting_label",
    "setting_value_label",
]

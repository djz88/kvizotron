"""Admin forms. Question forms are not here: each question type reads its own (`parse_admin`)."""

from collections.abc import Mapping, Sequence
from typing import Any

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from app.api.i18n import PUBLIC_LOCALES
from app.contracts import QuestionTypePlugin
from app.domain import questions, settings
from app.domain.models import Quiz, QuizRevision

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
    store = form.cleaned_data.get(settings.STORE_ANSWERS) or settings.resolve(
        settings.STORE_ANSWERS
    )
    visibility = form.cleaned_data.get(settings.ANSWERS_VISIBILITY) or settings.resolve(
        settings.ANSWERS_VISIBILITY
    )
    if settings.is_visibility_conflict(store, visibility):
        form.add_error(
            settings.ANSWERS_VISIBILITY,
            _("Showing answers to anyone but admins needs all answers stored."),
        )


def _value_choices(key: str) -> list[tuple[str, Any]]:
    definition = settings.CATALOGUE[key]
    return [(value, definition.value_labels[value]) for value in definition.choices]


class GlobalSettingsForm(forms.Form):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for key in settings.keys_for("global"):
            definition = settings.CATALOGUE[key]
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
        return cleaned


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
            self.fields[key] = forms.ChoiceField(
                label=definition.label,
                help_text=definition.help or "",
                choices=[("", inherit), *_value_choices(key)],
                initial=settings.quiz_override(key, quiz) or "",
                required=False,
            )

    def clean_slug(self) -> str:
        return _slug_is_free(self.cleaned_data["slug"], self.quiz)

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        _refuse_flow_conflict(self)
        _refuse_visibility_conflict(self)
        return cleaned

    def apply_to(self, quiz: Quiz) -> None:
        quiz.slug = self.cleaned_data["slug"]
        quiz.featured = self.cleaned_data["featured"]
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

"""Admin forms. Question forms are not here: each question type reads its own (`parse_admin`)."""

from typing import Any

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from app.api.i18n import PUBLIC_LOCALES
from app.domain.models import Quiz, QuizRevision

LOCALE_CHOICES = [(code, code) for code in PUBLIC_LOCALES]


class LoginForm(forms.Form):
    login = forms.CharField(label=gettext_lazy("Login"), max_length=150)
    password = forms.CharField(
        label=gettext_lazy("Password"), strip=False, widget=forms.PasswordInput
    )


class QuizForm(forms.Form):
    slug = forms.SlugField(
        label=gettext_lazy("URL identifier"),
        max_length=80,
        help_text=gettext_lazy(
            "Locked after the first publication, so that printed QR codes work."
        ),
    )
    supported_locales = forms.MultipleChoiceField(
        label=gettext_lazy("Languages"),
        choices=LOCALE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    default_locale = forms.ChoiceField(
        label=gettext_lazy("Default language"), choices=LOCALE_CHOICES
    )
    featured = forms.BooleanField(label=gettext_lazy("Highlight on the home page"), required=False)

    def __init__(self, *args: Any, quiz: Quiz | None = None, **kwargs: Any) -> None:
        self.quiz = quiz
        if quiz is not None:
            kwargs.setdefault(
                "initial",
                {
                    "slug": quiz.slug,
                    "supported_locales": quiz.supported_locales,
                    "default_locale": quiz.default_locale,
                    "featured": quiz.featured,
                    **{f"title_{code}": text for code, text in quiz.title.items()},
                },
            )
        super().__init__(*args, **kwargs)
        for code in PUBLIC_LOCALES:
            self.fields[f"title_{code}"] = forms.CharField(
                label=f"{_('Title')} ({code})", max_length=200, required=False
            )
        if quiz is not None and quiz.revisions.exclude(status=QuizRevision.Status.DRAFT).exists():
            self.fields["slug"].disabled = True

    def clean_slug(self) -> str:
        slug = self.cleaned_data["slug"]
        others = Quiz.objects.filter(slug=slug)
        if self.quiz is not None:
            others = others.exclude(pk=self.quiz.pk)
        if others.exists():
            raise forms.ValidationError(_("Another quiz already uses this identifier."))
        return slug

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
        quiz.slug = data["slug"]
        quiz.supported_locales = data["supported_locales"]
        quiz.default_locale = data["default_locale"]
        quiz.featured = data["featured"]
        quiz.title = {
            code: data[f"title_{code}"] for code in PUBLIC_LOCALES if data[f"title_{code}"]
        }
        quiz.save()
        return quiz


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

"""Branding form and the colour fields shared with the settings forms."""

from typing import Any

from django import forms
from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from app.contracts import (
    CUSTOM_PALETTE,
    BrandColours,
)
from app.domain import (
    branding,
)
from app.domain.models import Quiz


class ColourInput(forms.TextInput):
    """A colour picker; a browser without one, or without JavaScript, shows a text field."""

    input_type = "color"


COLOUR_NAMES = ("main", "accent")


def _add_colour_fields(form: forms.Form, quiz: Quiz | None) -> None:
    """The custom colours sit with the palette, so that both save together."""
    if "colours" not in branding.theme().branding_fields():
        return
    shown = branding.shown_colours(quiz)
    labels = {"main": _("Main colour"), "accent": _("Accent colour")}
    for name in COLOUR_NAMES:
        form.fields[name] = forms.CharField(
            label=labels[name],
            help_text=_("Used with the palette Custom colours, as #rrggbb."),
            max_length=7,
            required=False,
            widget=ColourInput,
            initial=getattr(shown, name),
        )


def _clean_colours(form: forms.Form, palette: str) -> None:
    """`palette` is the one that will apply at this level, empty when it follows the global one."""
    if "main" not in form.fields:
        return
    typed = {name: str(form.cleaned_data.get(name) or "").strip() for name in COLOUR_NAMES}
    for name, value in typed.items():
        if value and not branding.HEX.fullmatch(value):
            form.add_error(name, _("A colour is #rrggbb."))
    if palette != CUSTOM_PALETTE or any(form.has_error(name) for name in COLOUR_NAMES):
        return
    stored = branding.colours_of(getattr(form, "quiz", None))
    submitted = BrandColours(typed["main"], typed["accent"]) if all(typed.values()) else None
    partial = any(typed.values()) and submitted is None
    try:
        if partial:
            raise branding.ColoursMissing()
        branding.require_colours(palette, submitted or stored)
    except branding.ColoursMissing:
        form.add_error("main", _("Choose both colours for custom colours."))


def _save_colours(form: forms.Form, palette: str, quiz: Quiz | None, admin_id: str) -> None:
    """Colours count only with `custom`: a colour input always sends a value."""
    if "main" not in form.fields or palette != CUSTOM_PALETTE:
        return
    typed = [str(form.cleaned_data.get(name) or "").strip().lower() for name in COLOUR_NAMES]
    if all(typed) and BrandColours(*typed) != branding.colours_of(quiz):
        branding.set_colours(quiz, BrandColours(*typed), admin_id=admin_id)


BRANDING_LABELS = {
    "name": gettext_lazy("Name in the top bar"),
    "motto": gettext_lazy("Motto"),
    "footer": gettext_lazy("Footer"),
}


ADDRESS_HELP = gettext_lazy(
    "Fetched and kept as a copy when you save. Participants never see the address."
)


class BrandingForm(forms.Form):
    """Name, motto, footer and logo of the pages. Only what the theme lets an admin change.

    Texts per language; an empty English or Ukrainian text shows the Czech one. At a quiz, a
    field with every language empty is no override. The colours are not here: they save with
    the palette.
    """

    def __init__(self, *args: Any, quiz: Quiz | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.quiz = quiz
        allowed = branding.theme().branding_fields()
        stored = branding.texts_of(quiz)
        self.text_fields = [name for name in branding.TEXT_LIMITS if name in allowed]
        for name in self.text_fields:
            for code in branding.LOCALES:
                self.fields[f"{name}_{code}"] = forms.CharField(
                    label=f"{BRANDING_LABELS[name]} ({code})",
                    max_length=branding.TEXT_LIMITS[name],
                    required=False,
                    initial=stored.get(name, {}).get(code, ""),
                )
        if "footer" in allowed:
            self.fields[branding.CONTACT_EMAIL] = forms.EmailField(
                label=gettext_lazy("Contact e-mail"),
                max_length=branding.EMAIL_LIMIT,
                required=False,
                initial=stored.get(branding.CONTACT_EMAIL, {}).get("cs", ""),
                help_text=(
                    gettext_lazy(
                        "Shown publicly in the footer of every page "
                        "that sets no contact of its own."
                    )
                    if quiz is None
                    else gettext_lazy(
                        "Shown publicly in the footer. "
                        "Empty: the e-mail of the admin who created the quiz."
                    )
                ),
            )
        if "logo" in allowed:
            self.fields["logo"] = forms.FileField(label=gettext_lazy("Logo"), required=False)
            self.fields["logo_source"] = forms.URLField(
                label=gettext_lazy("Or a logo address"),
                required=False,
                max_length=2000,
                initial=branding.logo_source(quiz) or "",
                help_text=ADDRESS_HELP,
            )
            self.fields["remove_logo"] = forms.BooleanField(
                label=gettext_lazy("Remove the logo"), required=False
            )
        if "hero_logo" in allowed:
            self.fields["hero_logo"] = forms.FileField(
                label=gettext_lazy("Landing page logo"),
                required=False,
                help_text=gettext_lazy(
                    "Shown large and centred on the home page. Empty: the built-in logo."
                ),
            )
            self.fields["hero_logo_source"] = forms.URLField(
                label=gettext_lazy("Or a landing page logo address"),
                required=False,
                max_length=2000,
                initial=branding.hero_logo_source(quiz) or "",
                help_text=ADDRESS_HELP,
            )
            self.fields["remove_hero_logo"] = forms.BooleanField(
                label=gettext_lazy("Remove the landing page logo"), required=False
            )

    def _image_changes(self) -> dict[str, branding.ImageChange]:
        """A file wins over removal and removal over an address; the others change nothing."""
        changes: dict[str, branding.ImageChange] = {}
        for field in branding.IMAGE_FIELDS:
            upload = self.cleaned_data.get(field)
            address = self.cleaned_data.get(f"{field}_source")
            if upload:
                changes[field] = branding.Upload(upload.read(), upload.name)
            elif self.cleaned_data.get(f"remove_{field}"):
                changes[field] = branding.Remove()
            elif address:
                changes[field] = branding.Address(address)
        return changes

    def save(self, admin_id: str) -> None:
        """Raises `ImageRefused` with the field blamed, before anything else changes."""
        try:
            branding.set_images(self.quiz, self._image_changes(), admin_id=admin_id)
        except branding.ImageChangeRefused as error:
            self.add_error(
                f"{error.field}_source" if error.address else error.field,
                f"{error.label}: {error}",
            )
            raise
        stored = branding.texts_of(self.quiz)
        with transaction.atomic():  # the texts and the contact e-mail together; files are above
            for name in self.text_fields:
                typed = {
                    code: self.cleaned_data[f"{name}_{code}"].strip() for code in branding.LOCALES
                }
                typed = {code: text for code, text in typed.items() if text}
                if typed != stored.get(name, {}):
                    branding.set_texts(self.quiz, name, typed, admin_id=admin_id)
            if branding.CONTACT_EMAIL in self.fields:
                email = self.cleaned_data[branding.CONTACT_EMAIL].strip()
                if email != stored.get(branding.CONTACT_EMAIL, {}).get("cs", ""):
                    branding.set_contact_email(self.quiz, email, admin_id=admin_id)

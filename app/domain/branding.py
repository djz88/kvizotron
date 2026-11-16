"""Branding: name, motto, logo, colours and footer of the pages.

A quiz overrides each field on its own; what it leaves alone follows the global value, which
follows the built-in one. The palette and the custom colours resolve as one unit from the level
that chose `custom`. Changes take effect at once, create no draft and are audited by field name.
The domain owns the table and the rules; the theme owns the palettes and the derivation (ADR-0054).
"""

import colorsys
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.db import transaction
from django.urls import reverse
from django.utils.translation import gettext, override

from app.contracts import (
    COLOR_PALETTE,
    CUSTOM_PALETTE,
    BrandColours,
    DerivedPalette,
    ImageRefused,
    MediaStorageProvider,
    ThemePlugin,
)
from app.domain import authoring, external_images, settings
from app.domain.creator import creator_email
from app.domain.models import AppSetting, BrandingConfiguration, Quiz
from app.kernel import audit, registry

logger = logging.getLogger(__name__)
LOCALES = ("cs", "en", "uk")
TEXT_LIMITS = {"name": 80, "motto": 160, "footer": 300}
DEFAULT_NAME = "Kvízotron"
LOGO_FAMILIES = ("aurora", "mint", "amber")
PRESET_FAMILY = {  # the built-in logo that goes with each preset
    "indigo_pink": "aurora",
    "violet_white": "aurora",
    "blue_teal": "mint",
    "green_blue": "mint",
    "red_plum": "amber",
}
DEFAULT_COLOURS = BrandColours("#1769e0", "#ffb020")  # the default preset's main and accent
CONTACT_EMAIL = "contact_email"  # in `texts_json` as {"cs": address}
EMAIL_LIMIT = 254
HEX = re.compile(r"#[0-9a-fA-F]{6}")


class ColoursMissing(Exception):
    """`custom` colours were chosen without both colours."""


@dataclass(frozen=True)
class Branding:
    name: str
    motto: str
    footer: str
    contact_email: str  # quiz, global, the quiz creator's account e-mail; "" without a quiz
    logo_url: str
    hero_logo_url: str
    hero_logo_dark_url: str | None  # the dark twin of a built-in hero logo; None for a chosen one
    about_logo_url: str  # the About page: the built-in full logo, or the chosen large logo
    about_logo_dark_url: str | None
    logo_family: str
    logo_label: str | None  # file name or address of a chosen logo; None for the built-in one
    hero_logo_label: str | None
    show_hero_logo: bool  # the home and About pages
    quiz_hero_logo: bool  # a quiz page, only for the quiz's own large logo
    palette: str
    custom: DerivedPalette | None
    sources: Mapping[str, str]  # field -> "quiz", "global" or "default"


def _asset(family: str, kind: str) -> str:
    return f"/assets/logo-{family}-{kind}.svg"


def logo_family(palette: str, custom: DerivedPalette | None) -> str:
    """Which built-in logo goes with a palette; a custom palette by the hue of its main colour."""
    if palette != CUSTOM_PALETTE or custom is None:
        return PRESET_FAMILY[palette]
    value = custom.main.lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    hue = colorsys.rgb_to_hls(red, green, blue)[0] * 360
    if hue < 70 or hue >= 330:
        return "amber"
    return "mint" if hue < 200 else "aurora"


def theme() -> ThemePlugin:
    return cast(ThemePlugin, registry.get("theme", registry.keys("theme")[0]))


def media() -> MediaStorageProvider:
    keys = registry.keys("media_storage")
    if not keys:
        raise LookupError("media_storage")
    return cast(MediaStorageProvider, registry.get("media_storage", keys[0]))


def _row(quiz: Quiz | None) -> BrandingConfiguration | None:
    return BrandingConfiguration.objects.filter(quiz=quiz).first()


def _levels(quiz: Quiz | None) -> list[tuple[str, BrandingConfiguration | None]]:
    levels: list[tuple[str, BrandingConfiguration | None]] = []
    if quiz is not None:
        levels.append(("quiz", _row(quiz)))
    levels.append(("global", _row(None)))
    return levels


def _text(texts: Mapping[str, str], locale: str) -> str:
    for candidate in (locale, "cs", *LOCALES):
        if texts.get(candidate):
            return texts[candidate]
    return ""


def _chosen_text(
    levels: list[tuple[str, BrandingConfiguration | None]], field: str, locale: str
) -> tuple[str, str] | None:
    for source, row in levels:
        texts = row.texts_json.get(field, {}) if row else {}
        if any(texts.values()):
            return _text(texts, locale), source
    return None


def _colours_of(row: BrandingConfiguration | None) -> BrandColours | None:
    tokens = row.tokens_json if row else {}
    if tokens.get("main") and tokens.get("accent"):
        return BrandColours(tokens["main"], tokens["accent"])
    return None


def colours_of(quiz: Quiz | None) -> BrandColours | None:
    """The colours stored at that level, for a form that checks `custom` against them."""
    return _colours_of(_row(quiz))


def shown_colours(quiz: Quiz | None) -> BrandColours:
    """A colour input starts with this level's colours, else the global ones, else the default."""
    return colours_of(quiz) or colours_of(None) or DEFAULT_COLOURS


def texts_of(quiz: Quiz | None) -> dict[str, dict[str, str]]:
    """What is stored at that level, per field and language, for a form to start with."""
    row = _row(quiz)
    return {field: dict(texts) for field, texts in row.texts_json.items()} if row else {}


def _asset_entry(row: BrandingConfiguration | None, field: str) -> dict[str, str | None] | None:
    """`assets_json[field]` as {asset, source, name}; an older row has no source or no name."""
    raw = row.assets_json.get(field) if row else None
    if not raw:
        return None
    if isinstance(raw, str):
        return {"asset": raw, "source": None, "name": None}
    return {"asset": raw.get("asset"), "source": raw.get("source"), "name": raw.get("name")}


def _has_asset(quiz: Quiz | None, field: str) -> bool:
    entry = _asset_entry(_row(quiz), field)
    return bool(entry and entry["asset"])


def has_logo(quiz: Quiz | None) -> bool:
    return _has_asset(quiz, "logo")


def has_hero_logo(quiz: Quiz | None) -> bool:
    return _has_asset(quiz, "hero_logo")


def _palette_source(quiz: Quiz | None) -> str:
    if quiz is not None and settings.quiz_override(COLOR_PALETTE, quiz) is not None:
        return "quiz"
    if AppSetting.objects.filter(key=COLOR_PALETTE, quiz__isnull=True).exists():
        return "global"
    return "default"


def resolve(quiz: Quiz | None, locale: str) -> Branding:
    levels = _levels(quiz)
    sources: dict[str, str] = {}
    texts: dict[str, str] = {}
    for field in TEXT_LIMITS:
        chosen = _chosen_text(levels, field, locale)
        texts[field], sources[field] = chosen if chosen else ("", "default")
    if sources["name"] == "default":
        texts["name"] = DEFAULT_NAME
    if sources["motto"] == "default":
        with override(locale):
            texts["motto"] = gettext("Turn on your brain. Start Kvízotron.")
    chosen_email = _chosen_text(levels, CONTACT_EMAIL, locale)
    if chosen_email:
        texts[CONTACT_EMAIL], sources[CONTACT_EMAIL] = chosen_email
    else:
        texts[CONTACT_EMAIL] = creator_email(quiz) if quiz is not None else ""
        sources[CONTACT_EMAIL] = "creator" if texts[CONTACT_EMAIL] else "default"
    palette = settings.resolve(COLOR_PALETTE, quiz)
    sources["colours"] = _palette_source(quiz)
    custom = None
    if palette == CUSTOM_PALETTE:
        chooser = "quiz" if sources["colours"] == "quiz" else "global"
        colours = _colours_of(dict(levels)[chooser])
        if colours is None:  # chosen without colours: show the default instead of nothing
            palette = settings.CATALOGUE[COLOR_PALETTE].default
        else:
            custom = theme().derive_palette(colours)
    family = logo_family(palette, custom)
    logo_url, sources["logo"] = _asset(family, "bar"), "default"
    logo_label = hero_logo_label = None
    for source, row in levels:
        entry = _asset_entry(row, "logo")
        if entry and entry["asset"]:
            logo_url, sources["logo"] = reverse("media", args=[entry["asset"]]), source
            logo_label = entry["name"] or entry["source"]
            break
    hero_logo_url, sources["hero_logo"] = _asset(family, "hero-light"), "default"
    hero_logo_dark_url: str | None = _asset(family, "hero-dark")
    about_logo_url = _asset(family, "about-light")
    about_logo_dark_url: str | None = _asset(family, "about-dark")
    for source, row in levels:
        entry = _asset_entry(row, "hero_logo")
        if entry and entry["asset"]:
            hero_logo_url, sources["hero_logo"] = reverse("media", args=[entry["asset"]]), source
            hero_logo_dark_url = about_logo_dark_url = None
            about_logo_url = hero_logo_url
            hero_logo_label = entry["name"] or entry["source"]
            break
    show_hero_logo = settings.resolve(settings.SHOW_HERO_LOGO) == settings.Switch.ON
    quiz_hero_logo = quiz is not None and sources["hero_logo"] == "quiz"
    return Branding(
        name=texts["name"],
        motto=texts["motto"],
        footer=texts["footer"],
        contact_email=texts[CONTACT_EMAIL],
        logo_url=logo_url,
        hero_logo_url=hero_logo_url,
        hero_logo_dark_url=hero_logo_dark_url,
        about_logo_url=about_logo_url,
        about_logo_dark_url=about_logo_dark_url,
        logo_family=family,
        logo_label=logo_label,
        hero_logo_label=hero_logo_label,
        show_hero_logo=show_hero_logo,
        quiz_hero_logo=quiz_hero_logo,
        palette=palette,
        custom=custom,
        sources=sources,
    )


@dataclass(frozen=True)
class QuizMark:
    """What a quiz's own branding adds to its tile on the landing page."""

    name: str  # the quiz's own name in the page language; "" without one
    logo_url: str | None  # the quiz's own logo; None without one


def quiz_marks(quizzes: Sequence[Quiz], locale: str) -> dict[UUID, QuizMark]:
    """The own name and logo of each quiz that sets one, from one query.

    The global name and logo are the page's own; a tile shows only what tells a quiz apart.
    """
    marks: dict[UUID, QuizMark] = {}
    for row in BrandingConfiguration.objects.filter(quiz__in=quizzes):
        chosen = _chosen_text([("quiz", row)], "name", locale)
        entry = _asset_entry(row, "logo")
        logo_url = reverse("media", args=[entry["asset"]]) if entry and entry["asset"] else None
        name = chosen[0] if chosen else ""
        if name or logo_url:
            marks[cast(UUID, row.quiz_id)] = QuizMark(name, logo_url)
    return marks


def require_colours(palette: str, colours: BrandColours | None) -> None:
    """The form layer's check: `custom` needs both colours, those submitted or those stored."""
    if palette == CUSTOM_PALETTE and colours is None:
        raise ColoursMissing()


def _checked_hex(value: str) -> str:
    if not HEX.fullmatch(value):
        raise ValueError("A colour is #rrggbb.")
    return value.lower()


def _editable(quiz: Quiz | None) -> None:
    if quiz is not None:
        authoring.ensure_editable(quiz)


def _save(
    quiz: Quiz | None, field: str, admin_id: str, **changes: object
) -> BrandingConfiguration | None:
    """Writes columns of the level's row, drops an emptied row and audits the field name."""
    row = _row(quiz) or BrandingConfiguration(quiz=quiz, theme_id=theme().id)
    for column, value in changes.items():
        setattr(row, column, value)
    if row.texts_json or row.tokens_json or row.assets_json:
        row.save()
    elif row.pk:
        row.delete()
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action="branding.changed",
        entity_type="branding",
        entity_id=str(quiz.id) if quiz else "global",
        details={"field": field},
    )
    return row


def set_texts(quiz: Quiz | None, field: str, values: Mapping[str, str], *, admin_id: str) -> None:
    if field not in TEXT_LIMITS:
        raise ValueError(field)
    cleaned = {
        locale: values.get(locale, "").strip()
        for locale in LOCALES
        if values.get(locale, "").strip()
    }
    if any(len(text) > TEXT_LIMITS[field] for text in cleaned.values()):
        raise ValueError(f"{field} is longer than {TEXT_LIMITS[field]} characters.")
    with transaction.atomic():
        _editable(quiz)
        row = _row(quiz)
        texts = dict(row.texts_json) if row else {}
        if cleaned:
            texts[field] = cleaned
        else:
            texts.pop(field, None)
        _save(quiz, field, admin_id, texts_json=texts)


def set_contact_email(quiz: Quiz | None, email: str, *, admin_id: str) -> None:
    """An empty address removes the override. Raises ValueError for an invalid one."""
    email = email.strip()
    if email:
        try:
            if len(email) > EMAIL_LIMIT:
                raise ValidationError("too long")
            EmailValidator()(email)
        except ValidationError as error:
            raise ValueError("Enter a valid e-mail address.") from error
    with transaction.atomic():
        _editable(quiz)
        row = _row(quiz)
        texts = dict(row.texts_json) if row else {}
        if email:
            texts[CONTACT_EMAIL] = {"cs": email}
        else:
            texts.pop(CONTACT_EMAIL, None)
        _save(quiz, CONTACT_EMAIL, admin_id, texts_json=texts)


def _asset_ids(row: BrandingConfiguration) -> set[str]:
    entries = (_asset_entry(row, field) for field in row.assets_json)
    return {entry["asset"] for entry in entries if entry and entry["asset"]}


def _unused(asset_id: str) -> bool:
    return not any(asset_id in _asset_ids(row) for row in BrandingConfiguration.objects.all())


IMAGE_FIELDS = ("logo", "hero_logo")


@dataclass(frozen=True)
class Upload:
    data: bytes
    name: str


@dataclass(frozen=True)
class Address:
    url: str


@dataclass(frozen=True)
class Remove:
    pass


ImageChange = Upload | Address | Remove


class ImageChangeRefused(ImageRefused):
    """An image of a save was refused: the field, what to call it, and whether it was an address."""

    def __init__(self, field: str, label: str, reason: str, *, address: bool) -> None:
        super().__init__(reason)
        self.field = field
        self.label = label
        self.address = address


def _asset_source(quiz: Quiz | None, field: str) -> str | None:
    entry = _asset_entry(_row(quiz), field)
    return entry["source"] if entry else None


def logo_source(quiz: Quiz | None) -> str | None:
    """The address the level's logo was fetched from; None for an upload or no logo."""
    return _asset_source(quiz, "logo")


def hero_logo_source(quiz: Quiz | None) -> str | None:
    return _asset_source(quiz, "hero_logo")


def _discard_unused(asset_id: str) -> None:
    if _unused(asset_id):
        media().delete_image(asset_id)


FILE_NAME_LIMIT = 80


def _file_name(raw: str) -> str | None:
    """The base name of an uploaded file, to show which logo is set; never a path."""
    base = raw.replace("\\", "/").rsplit("/", 1)[-1]
    clean = "".join(ch for ch in base if ch.isprintable()).strip()
    return clean[:FILE_NAME_LIMIT] or None


def _stage(
    field: str, change: Upload | Address, deadline: float
) -> tuple[str, str | None, str | None]:
    """Stores a file or fetches an address; returns the asset id, its address and its file name."""
    storage = media()
    if isinstance(change, Upload):
        try:
            return storage.store_image(change.data), None, _file_name(change.name)
        except ImageRefused as error:
            raise ImageChangeRefused(field, change.name, str(error), address=False) from error
    try:
        storage.check_image_address(change.url)
        copy = storage.fetch_image(
            change.url, allow_internal=settings.internal_addresses_allowed(), deadline=deadline
        )
    except ImageRefused as error:
        raise ImageChangeRefused(field, change.url, str(error), address=True) from error
    return copy, change.url, None


def set_images(quiz: Quiz | None, changes: Mapping[str, ImageChange], *, admin_id: str) -> None:
    """Changes the logo and the landing page logo together, or neither (ADR-0054).

    Every file is stored and every address fetched first, within one limit for the save
    (ADR-0043); the first one refused raises `ImageChangeRefused` and nothing else happens. Then
    all fields are written in one transaction. An address equal to the stored one is not fetched
    again, and removing what is not there changes nothing.
    """
    if not set(changes) <= set(IMAGE_FIELDS):
        raise ValueError(sorted(set(changes) - set(IMAGE_FIELDS)))
    _editable(quiz)
    deadline = time.monotonic() + external_images.FETCHES_SECONDS
    staged: dict[str, tuple[str, str | None, str | None]] = {}
    removed: set[str] = set()
    replaced: list[str] = []
    try:
        for field, change in changes.items():
            if isinstance(change, Remove):
                if _has_asset(quiz, field):
                    removed.add(field)
            elif not (isinstance(change, Address) and change.url == _asset_source(quiz, field)):
                staged[field] = _stage(field, change, deadline)
        if not staged and not removed:
            return
        with transaction.atomic():
            _editable(quiz)
            for field in changes:
                if field not in staged and field not in removed:
                    continue
                row = _row(quiz)
                assets = dict(row.assets_json) if row else {}
                previous = _asset_entry(row, field)
                if field in staged:
                    assets[field] = {
                        "asset": staged[field][0],
                        "source": staged[field][1],
                        "name": staged[field][2],
                    }
                else:
                    assets.pop(field, None)
                _save(quiz, field, admin_id, assets_json=assets)
                if previous and previous["asset"]:
                    replaced.append(previous["asset"])
    except Exception:
        for asset_id, _source, _name in staged.values():
            _discard_unused(asset_id)
        raise
    for old in replaced:
        try:
            _discard_unused(old)
        except Exception:  # the change is saved; a file left behind is no reason to fail it
            logger.exception("Could not delete a replaced branding image")


def set_logo(quiz: Quiz | None, data: bytes, *, admin_id: str) -> None:
    set_images(quiz, {"logo": Upload(data, "")}, admin_id=admin_id)


def remove_logo(quiz: Quiz | None, *, admin_id: str) -> None:
    set_images(quiz, {"logo": Remove()}, admin_id=admin_id)


def set_hero_logo(quiz: Quiz | None, data: bytes, *, admin_id: str) -> None:
    set_images(quiz, {"hero_logo": Upload(data, "")}, admin_id=admin_id)


def remove_hero_logo(quiz: Quiz | None, *, admin_id: str) -> None:
    set_images(quiz, {"hero_logo": Remove()}, admin_id=admin_id)


def set_colours(
    quiz: Quiz | None, colours: BrandColours | None, *, admin_id: str
) -> DerivedPalette | None:
    """`None` clears them. Returns the colours that will be used, adjusted for contrast."""
    tokens: dict[str, str] = {}
    if colours is not None:
        tokens = {"main": _checked_hex(colours.main), "accent": _checked_hex(colours.accent)}
    with transaction.atomic():
        _editable(quiz)
        _save(quiz, "colours", admin_id, tokens_json=tokens)
    return theme().derive_palette(BrandColours(**tokens)) if tokens else None

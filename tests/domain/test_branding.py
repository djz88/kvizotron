"""Branding: a global identity and a per-field quiz override (AC-94, AC-95)."""

import io
import time
from pathlib import Path
from unittest import mock

import pytest
from django.db import IntegrityError, transaction
from django.utils import translation
from PIL import Image

from app.contracts import (
    ALLOW_INTERNAL_IMAGE_ADDRESSES,
    COLOR_PALETTE,
    CUSTOM_PALETTE,
    BrandColours,
    ImageRefused,
)
from app.domain import authoring, branding, external_images, settings
from app.domain.models import BrandingConfiguration
from app.kernel.models import AuditEvent
from app.providers.media_local import remote
from app.providers.media_local.models import MediaAsset
from tests.domain.helpers import ADMIN_ID, make_quiz

pytestmark = pytest.mark.django_db
LOGO_URL = "/assets/logo-mint-bar.svg"  # the default palette, blue_teal, is the mint family


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)


def png(colour="red"):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), colour).save(buffer, "PNG")
    return buffer.getvalue()


def asset_of(quiz):
    row = BrandingConfiguration.objects.get(quiz=quiz)
    return row.assets_json["logo"]["asset"]


def exists(asset_id):
    return branding.media().exists(asset_id)


def test_defaults_without_rows():
    """AC-94: with nothing stored the built-in identity is used."""
    with translation.override("cs"):
        result = branding.resolve(None, "cs")
    assert result.name == "Kvízotron"
    assert result.footer == ""
    assert result.logo_url == LOGO_URL
    assert result.custom is None
    assert set(result.sources.values()) == {"default"}
    assert set(result.sources) == {
        "name",
        "motto",
        "logo",
        "hero_logo",
        "colours",
        "footer",
        "contact_email",
    }


def test_global_name_reaches_a_quiz():
    """AC-94: a global name shows on a quiz that overrides nothing."""
    quiz = make_quiz()
    branding.set_texts(None, "name", {"cs": "Naše škola"}, admin_id=ADMIN_ID)
    result = branding.resolve(quiz, "cs")
    assert result.name == "Naše škola"
    assert result.sources["name"] == "global"
    assert result.sources["footer"] == "default"


def test_quiz_overrides_only_the_logo():
    """AC-95: a quiz that overrides the logo still follows later global changes."""
    quiz = make_quiz()
    branding.set_logo(quiz, png(), admin_id=ADMIN_ID)
    branding.set_texts(None, "name", {"cs": "Později"}, admin_id=ADMIN_ID)
    branding.set_texts(None, "footer", {"cs": "Patička"}, admin_id=ADMIN_ID)
    branding.set_colours(None, BrandColours("#336699", "#cc3300"), admin_id=ADMIN_ID)
    settings.set_global(COLOR_PALETTE, CUSTOM_PALETTE, admin_id=ADMIN_ID)
    result = branding.resolve(quiz, "cs")
    assert result.sources["logo"] == "quiz"
    assert result.logo_url != LOGO_URL
    assert (result.name, result.footer) == ("Později", "Patička")
    assert result.sources["name"] == result.sources["footer"] == "global"
    assert result.palette == CUSTOM_PALETTE
    assert result.custom is not None
    assert result.sources["colours"] == "global"


def test_hero_logo_is_independent_of_the_logo():
    """The landing page logo and the bar logo override separately."""
    quiz = make_quiz()
    branding.set_logo(quiz, png("red"), admin_id=ADMIN_ID)
    branding.set_hero_logo(quiz, png("blue"), admin_id=ADMIN_ID)
    result = branding.resolve(quiz, "cs")
    assert result.sources["logo"] == result.sources["hero_logo"] == "quiz"
    assert result.logo_url != result.hero_logo_url
    assert result.logo_url != LOGO_URL
    assert result.hero_logo_url != "/assets/logo-mint-hero-light.svg"


def test_replaced_hero_logo_deletes_the_old_asset():
    quiz = make_quiz()
    branding.set_hero_logo(quiz, png("red"), admin_id=ADMIN_ID)
    old = BrandingConfiguration.objects.get(quiz=quiz).assets_json["hero_logo"]["asset"]
    branding.set_hero_logo(quiz, png("blue"), admin_id=ADMIN_ID)
    assert not exists(old)
    branding.remove_hero_logo(quiz, admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "cs").hero_logo_url == "/assets/logo-mint-hero-light.svg"


def test_removing_the_hero_logo_does_not_touch_the_logo():
    quiz = make_quiz()
    branding.set_logo(quiz, png("red"), admin_id=ADMIN_ID)
    branding.set_hero_logo(quiz, png("blue"), admin_id=ADMIN_ID)
    branding.remove_hero_logo(quiz, admin_id=ADMIN_ID)
    result = branding.resolve(quiz, "cs")
    assert result.hero_logo_url == "/assets/logo-mint-hero-light.svg"
    assert result.sources["logo"] == "quiz" and result.logo_url != LOGO_URL


def test_refused_hero_logo_changes_nothing():
    with pytest.raises(ImageRefused):
        branding.set_hero_logo(None, b"not an image", admin_id=ADMIN_ID)
    assert branding.resolve(None, "cs").hero_logo_url == "/assets/logo-mint-hero-light.svg"


def test_blank_language_falls_back_to_czech():
    """AC-94: an empty English text shows the Czech one."""
    branding.set_texts(None, "motto", {"cs": "Heslo", "en": "", "uk": "Гасло"}, admin_id=ADMIN_ID)
    assert branding.resolve(None, "en").motto == "Heslo"
    assert branding.resolve(None, "uk").motto == "Гасло"


def test_all_blank_passes_to_the_next_level():
    """AC-95: a quiz text with every language blank is no override."""
    quiz = make_quiz()
    branding.set_texts(None, "name", {"cs": "Globální"}, admin_id=ADMIN_ID)
    branding.set_texts(quiz, "name", {"cs": "Kvízová"}, admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "cs").sources["name"] == "quiz"
    branding.set_texts(quiz, "name", {"cs": " ", "en": ""}, admin_id=ADMIN_ID)
    result = branding.resolve(quiz, "cs")
    assert (result.name, result.sources["name"]) == ("Globální", "global")
    branding.set_texts(None, "name", {}, admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "cs").sources["name"] == "default"


def test_text_limits_are_enforced():
    """AC-94: name 80, motto 160 and footer 300 characters."""
    with pytest.raises(ValueError):
        branding.set_texts(None, "name", {"cs": "x" * 81}, admin_id=ADMIN_ID)
    with pytest.raises(ValueError):
        branding.set_texts(None, "footer", {"cs": "x" * 301}, admin_id=ADMIN_ID)
    branding.set_texts(None, "footer", {"cs": "x" * 300}, admin_id=ADMIN_ID)


def test_custom_colours_come_from_the_level_that_chose_them():
    """AC-95: a quiz preset override removed brings the global custom colours back."""
    quiz = make_quiz()
    branding.set_colours(None, BrandColours("#336699", "#cc3300"), admin_id=ADMIN_ID)
    settings.set_global(COLOR_PALETTE, CUSTOM_PALETTE, admin_id=ADMIN_ID)
    settings.set_override(COLOR_PALETTE, quiz, "red_plum", admin_id=ADMIN_ID)
    result = branding.resolve(quiz, "cs")
    assert (result.palette, result.custom) == ("red_plum", None)
    assert result.sources["colours"] == "quiz"
    settings.set_override(COLOR_PALETTE, quiz, None, admin_id=ADMIN_ID)
    result = branding.resolve(quiz, "cs")
    assert result.palette == CUSTOM_PALETTE
    assert result.custom is not None
    assert result.custom.main == "#336699"
    assert result.sources["colours"] == "global"


def test_quiz_custom_colours_beat_global_ones():
    """AC-95: the quiz's own custom colours are used when the quiz chose custom."""
    quiz = make_quiz()
    branding.set_colours(None, BrandColours("#336699", "#cc3300"), admin_id=ADMIN_ID)
    settings.set_global(COLOR_PALETTE, CUSTOM_PALETTE, admin_id=ADMIN_ID)
    branding.set_colours(quiz, BrandColours("#003300", "#009900"), admin_id=ADMIN_ID)
    settings.set_override(COLOR_PALETTE, quiz, CUSTOM_PALETTE, admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "cs").custom.main == "#003300"
    assert branding.resolve(None, "cs").custom.main == "#336699"


def test_colours_are_stored_lower_case_and_validated():
    """AC-94: only #rrggbb is accepted."""
    derived = branding.set_colours(None, BrandColours("#FFFF00", "#FFFF00"), admin_id=ADMIN_ID)
    assert derived is not None and derived.adjusted
    assert BrandingConfiguration.objects.get(quiz=None).tokens_json == {
        "main": "#ffff00",
        "accent": "#ffff00",
    }
    for bad in ("red", "#12345", "#12345g", "#1234567"):
        with pytest.raises(ValueError):
            branding.set_colours(None, BrandColours(bad, "#000000"), admin_id=ADMIN_ID)
    assert branding.set_colours(None, None, admin_id=ADMIN_ID) is None
    assert not BrandingConfiguration.objects.exists()


def test_custom_needs_both_colours():
    """AC-94: custom without colours is refused by `require_colours`."""
    with pytest.raises(branding.ColoursMissing):
        branding.require_colours(CUSTOM_PALETTE, None)
    branding.require_colours("blue_teal", None)
    branding.require_colours(CUSTOM_PALETTE, BrandColours("#336699", "#cc3300"))


def test_replaced_logo_deletes_the_old_asset():
    """AC-95: a replaced logo file is deleted."""
    quiz = make_quiz()
    branding.set_logo(quiz, png("red"), admin_id=ADMIN_ID)
    first = asset_of(quiz)
    branding.set_logo(quiz, png("blue"), admin_id=ADMIN_ID)
    assert asset_of(quiz) != first
    assert not exists(first)
    second = asset_of(quiz)
    branding.remove_logo(quiz, admin_id=ADMIN_ID)
    assert not exists(second)
    assert branding.resolve(quiz, "cs").logo_url == LOGO_URL


def test_shared_asset_is_kept():
    """AC-95: removing the global logo keeps a file another level still uses."""
    quiz = make_quiz()
    branding.set_logo(None, png(), admin_id=ADMIN_ID)
    shared = BrandingConfiguration.objects.get(quiz=None).assets_json["logo"]["asset"]
    BrandingConfiguration.objects.create(
        quiz=quiz, theme_id="default", assets_json={"logo": shared}
    )
    branding.remove_logo(None, admin_id=ADMIN_ID)
    assert exists(shared)
    branding.remove_logo(quiz, admin_id=ADMIN_ID)
    assert not exists(shared)


def test_refused_logo_changes_nothing():
    """AC-94: a file the provider refuses leaves the logo as it was."""
    with pytest.raises(ImageRefused):
        branding.set_logo(None, b"not an image", admin_id=ADMIN_ID)
    assert not BrandingConfiguration.objects.exists()


def test_changes_are_audited_by_field_name_only():
    """AC-94: the audit row names fields and never values."""
    quiz = make_quiz()
    branding.set_texts(quiz, "name", {"cs": "Tajný název"}, admin_id=ADMIN_ID)
    branding.set_colours(quiz, BrandColours("#336699", "#cc3300"), admin_id=ADMIN_ID)
    events = list(AuditEvent.objects.filter(action="branding.changed").order_by("created_at"))
    assert [event.details_json["field"] for event in events] == ["name", "colours"]
    assert all(event.entity_id == str(quiz.id) for event in events)
    assert "Tajný" not in str([event.details_json for event in events])
    assert "#336699" not in str([event.details_json for event in events])


def test_an_archived_quiz_is_not_edited():
    """AC-95: archiving keeps the branding but refuses changes."""
    quiz = make_quiz()
    branding.set_texts(quiz, "name", {"cs": "Před"}, admin_id=ADMIN_ID)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        branding.set_texts(quiz, "name", {"cs": "Po"}, admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "cs").name == "Před"


def test_a_file_that_cannot_be_deleted_does_not_fail_a_saved_change(monkeypatch):
    quiz = make_quiz()
    branding.set_logo(quiz, png("red"), admin_id=ADMIN_ID)

    def broken(self, asset_id):
        raise OSError("disk gone")

    monkeypatch.setattr(type(branding.media()), "delete_image", broken)
    branding.remove_logo(quiz, admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "cs").logo_url == LOGO_URL


def test_a_second_global_row_is_refused():
    BrandingConfiguration.objects.create(quiz=None, theme_id="default")
    with pytest.raises(IntegrityError), transaction.atomic():
        BrandingConfiguration.objects.create(quiz=None, theme_id="default")


def test_custom_chosen_without_colours_anywhere_shows_the_default_preset():
    quiz = make_quiz()
    settings.set_override(COLOR_PALETTE, quiz, CUSTOM_PALETTE, admin_id=ADMIN_ID)
    result = branding.resolve(quiz, "cs")
    assert result.custom is None
    assert result.palette == settings.CATALOGUE[COLOR_PALETTE].default


def test_a_logo_of_an_archived_quiz_is_not_kept(tmp_path):
    quiz = make_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        branding.set_logo(quiz, png(), admin_id=ADMIN_ID)
    assert not list(tmp_path.iterdir())


def test_the_default_colours_are_those_of_the_default_preset():
    css = Path("app/plugins/theme_default/assets/theme.css").read_text()
    assert f"--kvz-main: {branding.DEFAULT_COLOURS.main};" in css
    assert f"--kvz-accent: {branding.DEFAULT_COLOURS.accent};" in css


def test_contact_email_quiz_then_global_then_creator():
    """AC-99."""
    from app.kernel.models import AdminUser

    admin = AdminUser.objects.create_admin("carol", "x-y-z-long-password-1")
    admin.email = "carol@example.org"
    admin.save()
    quiz = make_quiz(created_by=str(admin.pk))
    assert branding.resolve(quiz, "cs").contact_email == "carol@example.org"
    assert branding.resolve(None, "cs").contact_email == ""  # no fallback without a quiz
    branding.set_contact_email(None, "global@example.org", admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "cs").contact_email == "global@example.org"
    assert branding.resolve(None, "uk").contact_email == "global@example.org"
    branding.set_contact_email(quiz, "quiz@example.org", admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "en").contact_email == "quiz@example.org"
    branding.set_contact_email(quiz, "", admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "en").contact_email == "global@example.org"


@pytest.mark.parametrize("bad", ["nope", "a@b", "x" * 250 + "@example.org", "a b@example.org"])
def test_invalid_contact_email_is_refused(bad):
    with pytest.raises(ValueError):
        branding.set_contact_email(None, bad, admin_id=ADMIN_ID)
    assert not BrandingConfiguration.objects.exists()


def test_contact_email_audits_the_field_name_only():
    branding.set_contact_email(None, "secret@example.org", admin_id=ADMIN_ID)
    event = AuditEvent.objects.get(action="branding.changed")
    assert event.details_json == {"field": "contact_email"}


def test_an_uploaded_logo_is_stored_with_no_source():
    """A plain upload has no address to remember."""
    quiz = make_quiz()
    branding.set_logo(quiz, png(), admin_id=ADMIN_ID)
    row = BrandingConfiguration.objects.get(quiz=quiz)
    assert row.assets_json["logo"]["asset"]
    assert row.assets_json["logo"]["source"] is None


def test_a_legacy_plain_string_asset_still_resolves():
    """A row written before the address was stored holds a plain string, not a dict."""
    quiz = make_quiz()
    asset_id = branding.media().store_image(png())
    BrandingConfiguration.objects.create(
        quiz=quiz, theme_id="default", assets_json={"logo": asset_id}
    )
    assert branding.has_logo(quiz)
    assert branding.resolve(quiz, "cs").logo_url == f"/media/{asset_id}"


LOGO_ADDRESS = "https://logos.example/a.png"
OTHER_ADDRESS = "https://logos.example/b.png"


@pytest.fixture
def fetch(monkeypatch):
    fake = mock.Mock(side_effect=lambda *a, **k: png())
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


@pytest.fixture
def down(monkeypatch):
    fake = mock.Mock(side_effect=remote.RemoteRefused("down"))
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


def change(quiz, **changes):
    branding.set_images(quiz, changes, admin_id=ADMIN_ID)


def test_an_address_is_fetched_into_a_copy_and_its_source_kept(fetch):
    quiz = make_quiz()
    change(quiz, logo=branding.Address(LOGO_ADDRESS))
    assert branding.logo_source(quiz) == LOGO_ADDRESS
    assert branding.hero_logo_source(quiz) is None
    assert branding.resolve(quiz, "cs").logo_url == f"/media/{asset_of(quiz)}"
    assert exists(asset_of(quiz))


@pytest.mark.parametrize(
    "address",
    [
        "http://logos.example/a.png",
        "https://user:pw@logos.example/a.png",
        "ftp://logos.example/a.png",
    ],
)
def test_a_malformed_address_is_refused_before_any_fetch(fetch, address):
    with pytest.raises(branding.ImageChangeRefused) as raised:
        change(None, logo=branding.Address(address))
    assert (raised.value.field, raised.value.label, raised.value.address) == ("logo", address, True)
    fetch.assert_not_called()
    assert not BrandingConfiguration.objects.exists()


def test_an_unreachable_address_is_refused_and_names_the_field(down):
    with pytest.raises(branding.ImageChangeRefused) as raised:
        change(None, hero_logo=branding.Address(LOGO_ADDRESS))
    assert (raised.value.field, raised.value.address) == ("hero_logo", True)
    assert not BrandingConfiguration.objects.exists()


def test_an_internal_address_is_refused_unless_the_setting_allows_it(fetch, monkeypatch):
    monkeypatch.setattr(remote, "fetch", mock.Mock(side_effect=remote.RemoteInternal("internal")))
    with pytest.raises(branding.ImageChangeRefused):
        change(None, logo=branding.Address(LOGO_ADDRESS))
    monkeypatch.setattr(remote, "fetch", fetch)
    change(None, logo=branding.Address(LOGO_ADDRESS))
    assert fetch.call_args.kwargs["allow_internal"] is False
    settings.set_global(ALLOW_INTERNAL_IMAGE_ADDRESSES, "on", admin_id=ADMIN_ID)
    change(None, logo=branding.Address(OTHER_ADDRESS))
    assert fetch.call_args.kwargs["allow_internal"] is True


def test_an_unchanged_address_is_not_fetched_again(fetch):
    quiz = make_quiz()
    change(quiz, logo=branding.Address(LOGO_ADDRESS))
    first = asset_of(quiz)
    change(quiz, logo=branding.Address(LOGO_ADDRESS))
    assert fetch.call_count == 1
    assert asset_of(quiz) == first


def test_a_changed_address_replaces_the_copy_and_deletes_the_old_one(fetch):
    quiz = make_quiz()
    change(quiz, logo=branding.Address(LOGO_ADDRESS))
    first = asset_of(quiz)
    change(quiz, logo=branding.Address(OTHER_ADDRESS))
    assert not exists(first)
    assert branding.logo_source(quiz) == OTHER_ADDRESS


def test_removing_deletes_the_copy_and_removing_nothing_changes_nothing(fetch):
    quiz = make_quiz()
    change(quiz, logo=branding.Remove())
    assert not AuditEvent.objects.filter(action="branding.changed").exists()
    change(quiz, logo=branding.Address(LOGO_ADDRESS))
    copy = asset_of(quiz)
    change(quiz, logo=branding.Remove())
    assert not exists(copy)
    assert not branding.has_logo(quiz)


def test_both_addresses_are_fetched_within_one_shared_limit(monkeypatch):
    clock = [100.0]
    timeouts = []

    def slow_fetch(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        clock[0] += 1.0
        return png()

    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(remote, "fetch", slow_fetch)
    monkeypatch.setattr(external_images, "FETCHES_SECONDS", 3.0)
    change(None, logo=branding.Address(LOGO_ADDRESS), hero_logo=branding.Address(OTHER_ADDRESS))
    assert timeouts == [3.0, 2.0]
    assert MediaAsset.objects.count() == 2
    assert branding.logo_source(None) == LOGO_ADDRESS
    assert branding.hero_logo_source(None) == OTHER_ADDRESS


def test_an_exhausted_limit_refuses_the_next_address(fetch, monkeypatch):
    monkeypatch.setattr(external_images, "FETCHES_SECONDS", -1.0)
    monkeypatch.setattr(
        remote, "fetch", mock.Mock(side_effect=remote.RemoteRefused("no time left"))
    )
    with pytest.raises(branding.ImageChangeRefused):
        change(None, logo=branding.Address(LOGO_ADDRESS))
    assert not BrandingConfiguration.objects.exists()


def test_a_refused_image_leaves_no_copy_of_the_one_stored_before_it(down):
    with pytest.raises(branding.ImageChangeRefused):
        change(None, logo=branding.Upload(png(), "a.png"), hero_logo=branding.Address(LOGO_ADDRESS))
    assert not BrandingConfiguration.objects.exists()
    assert not MediaAsset.objects.exists()


def test_a_refused_file_leaves_no_copy_of_the_address_fetched_before_it(fetch):
    with pytest.raises(branding.ImageChangeRefused) as raised:
        change(
            None,
            logo=branding.Address(LOGO_ADDRESS),
            hero_logo=branding.Upload(b"not an image", "hero.png"),
        )
    assert (raised.value.field, raised.value.label, raised.value.address) == (
        "hero_logo",
        "hero.png",
        False,
    )
    assert not BrandingConfiguration.objects.exists()
    assert not MediaAsset.objects.exists()


def test_applying_both_fields_is_one_transaction(monkeypatch):
    real = branding._save

    def fails_on_the_second(quiz, field, admin_id, **changes):
        if field == "hero_logo":
            raise RuntimeError("database")
        return real(quiz, field, admin_id, **changes)

    monkeypatch.setattr(branding, "_save", fails_on_the_second)
    with pytest.raises(RuntimeError):
        change(
            None, logo=branding.Upload(png(), "a.png"), hero_logo=branding.Upload(png(), "b.png")
        )
    assert not BrandingConfiguration.objects.exists()
    assert not MediaAsset.objects.exists()


def test_an_archived_quiz_fetches_nothing(fetch):
    quiz = make_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        change(quiz, logo=branding.Address(LOGO_ADDRESS))
    fetch.assert_not_called()
    assert not MediaAsset.objects.exists()


def test_an_image_field_that_is_not_one_is_refused():
    with pytest.raises(ValueError):
        change(None, motto=branding.Remove())


def test_replacing_an_image_stored_in_the_older_shape_deletes_its_file():
    quiz = make_quiz()
    old = branding.media().store_image(png("red"))
    BrandingConfiguration.objects.create(quiz=quiz, theme_id="default", assets_json={"logo": old})
    assert branding.logo_source(quiz) is None
    branding.set_logo(quiz, png("blue"), admin_id=ADMIN_ID)
    assert not exists(old)
    assert asset_of(quiz) != old


def test_a_copy_two_rows_share_stays_until_the_last_one_lets_go():
    quiz = make_quiz()
    branding.set_logo(None, png(), admin_id=ADMIN_ID)
    shared = BrandingConfiguration.objects.get(quiz=None).assets_json["logo"]
    BrandingConfiguration.objects.create(
        quiz=quiz, theme_id="default", assets_json={"logo": shared}
    )
    branding.remove_logo(None, admin_id=ADMIN_ID)
    assert exists(shared["asset"])
    branding.remove_logo(quiz, admin_id=ADMIN_ID)
    assert not exists(shared["asset"])


@pytest.mark.parametrize(
    ("preset", "family"),
    [
        ("indigo_pink", "aurora"),
        ("violet_white", "aurora"),
        ("blue_teal", "mint"),
        ("green_blue", "mint"),
        ("red_plum", "amber"),
    ],
)
def test_preset_picks_its_logo_family(preset, family):
    assert branding.logo_family(preset, None) == family


@pytest.mark.parametrize(
    ("main", "family"),
    [
        ("#ff0000", "amber"),
        ("#ffa500", "amber"),
        ("#ff0066", "amber"),
        ("#00cc44", "mint"),
        ("#00ccff", "mint"),
        ("#2a4bff", "aurora"),
        ("#8a2be2", "aurora"),
        ("#cc22cc", "aurora"),
    ],
)
def test_custom_colour_picks_family_by_hue(main, family):
    """AC-148."""
    palette = branding.theme().derive_palette(BrandColours(main, "#ffb020"))
    assert branding.logo_family(CUSTOM_PALETTE, palette) == family


def test_every_preset_the_theme_offers_has_a_family():
    assert set(branding.theme().palettes()) <= set(branding.PRESET_FAMILY)


def test_default_logo_urls_follow_the_palette():
    """AC-148."""
    settings.set_global(COLOR_PALETTE, "red_plum", admin_id=ADMIN_ID)
    result = branding.resolve(None, "cs")
    assert result.logo_url == "/assets/logo-amber-bar.svg"
    assert result.hero_logo_url == "/assets/logo-amber-hero-light.svg"
    assert result.hero_logo_dark_url == "/assets/logo-amber-hero-dark.svg"
    assert result.about_logo_url == "/assets/logo-amber-about-light.svg"
    assert result.about_logo_dark_url == "/assets/logo-amber-about-dark.svg"
    assert result.logo_family == "amber"


def test_default_logo_follows_a_custom_palette():
    branding.set_colours(None, BrandColours("#00cc44", "#cc3300"), admin_id=ADMIN_ID)
    settings.set_global(COLOR_PALETTE, CUSTOM_PALETTE, admin_id=ADMIN_ID)
    assert branding.resolve(None, "cs").logo_family == "mint"


def test_uploaded_hero_logo_is_not_replaced_and_has_no_dark_twin():
    branding.set_hero_logo(None, png(), admin_id=ADMIN_ID)
    result = branding.resolve(None, "cs")
    assert result.hero_logo_url.startswith("/media/") and result.hero_logo_dark_url is None
    assert result.logo_url == LOGO_URL


def test_the_large_logo_is_shown_by_default():
    """AC-149."""
    assert branding.resolve(None, "cs").show_hero_logo is True


def test_the_large_logo_can_be_hidden_globally():
    settings.set_global(settings.SHOW_HERO_LOGO, "off", admin_id=ADMIN_ID)
    assert branding.resolve(None, "cs").show_hero_logo is False


def test_the_switch_is_global_only():
    assert settings.CATALOGUE[settings.SHOW_HERO_LOGO].scopes == ("global",)
    assert settings.CATALOGUE[settings.SHOW_HERO_LOGO].scope_reason


def test_a_quiz_shows_its_large_logo_only_when_it_has_its_own():
    """AC-150."""
    quiz = make_quiz()
    assert branding.resolve(quiz, "cs").quiz_hero_logo is False
    branding.set_hero_logo(None, png(), admin_id=ADMIN_ID)  # a global one is not the quiz's
    assert branding.resolve(quiz, "cs").quiz_hero_logo is False
    branding.set_hero_logo(quiz, png("blue"), admin_id=ADMIN_ID)
    assert branding.resolve(quiz, "cs").quiz_hero_logo is True


def test_there_is_no_quiz_large_logo_without_a_quiz():
    assert branding.resolve(None, "cs").quiz_hero_logo is False


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("logo.png", "logo.png"),
        ("../x/Logo škola.png", "Logo škola.png"),
        ("C:\\fakepath\\firma.png", "firma.png"),
        ("a\x00b\x1fc.png", "abc.png"),
        ("x" * 200 + ".png", ("x" * 200 + ".png")[:80]),
        ("", None),
        ("   ", None),
    ],
)
def test_the_file_name_of_an_upload_is_kept_as_a_plain_base_name(given, kept):
    quiz = make_quiz()
    branding.set_images(quiz, {"logo": branding.Upload(png(), given)}, admin_id=ADMIN_ID)
    assert BrandingConfiguration.objects.get(quiz=quiz).assets_json["logo"]["name"] == kept


def test_the_label_of_a_chosen_logo_is_its_file_name_or_its_address(fetch):
    quiz = make_quiz()
    assert branding.resolve(quiz, "cs").logo_label is None  # the built-in logo
    branding.set_images(quiz, {"logo": branding.Upload(png(), "firma.png")}, admin_id=ADMIN_ID)
    branding.set_images(quiz, {"hero_logo": branding.Address(LOGO_ADDRESS)}, admin_id=ADMIN_ID)
    result = branding.resolve(quiz, "cs")
    assert result.logo_label == "firma.png"
    assert result.hero_logo_label == LOGO_ADDRESS


def test_a_logo_stored_before_names_has_no_label():
    quiz = make_quiz()
    BrandingConfiguration.objects.create(
        quiz=quiz,
        theme_id="default",
        assets_json={"logo": {"asset": branding.media().store_image(png()), "source": None}},
    )
    assert branding.resolve(quiz, "cs").logo_label is None


def test_a_quiz_without_its_own_name_or_logo_has_no_mark():
    """AC-151."""
    quiz = make_quiz()
    branding.set_texts(None, "name", {"cs": "Globální"}, admin_id=ADMIN_ID)  # not the quiz's own
    assert branding.quiz_marks([quiz], "cs") == {}


def test_a_mark_has_the_own_name_in_the_page_language():
    quiz = make_quiz()
    branding.set_texts(quiz, "name", {"cs": "Škola", "en": "School"}, admin_id=ADMIN_ID)
    assert branding.quiz_marks([quiz], "en")[quiz.id] == branding.QuizMark("School", None)
    assert branding.quiz_marks([quiz], "uk")[quiz.id].name == "Škola"  # falls back to cs


def test_a_mark_has_the_own_logo_even_without_a_name():
    quiz = make_quiz()
    branding.set_logo(quiz, png(), admin_id=ADMIN_ID)
    mark = branding.quiz_marks([quiz], "cs")[quiz.id]
    assert mark.name == "" and mark.logo_url == f"/media/{asset_of(quiz)}"


def test_marks_of_several_quizzes_take_one_query(django_assert_num_queries):
    quizzes = [make_quiz(slug=f"q{n}") for n in range(4)]
    branding.set_texts(quizzes[0], "name", {"cs": "A"}, admin_id=ADMIN_ID)
    branding.set_logo(quizzes[1], png(), admin_id=ADMIN_ID)
    with django_assert_num_queries(1):
        marks = branding.quiz_marks(quizzes, "cs")
    assert set(marks) == {quizzes[0].id, quizzes[1].id}

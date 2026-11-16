"""AC-94, AC-95, AC-96: the admin forms for the application's and a quiz's branding."""

import io
import re
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from app.contracts import COLOR_PALETTE, CUSTOM_PALETTE, BrandColours
from app.domain import authoring, branding, settings
from app.domain.models import BrandingConfiguration, QuizRevision
from app.kernel.models import AuditEvent
from app.providers.media_local import remote
from app.providers.media_local.models import MediaAsset
from tests.domain.helpers import ADMIN_ID, make_quiz, published_quiz

pytestmark = pytest.mark.django_db
GLOBAL = "/admin/settings/branding"
CUSTOM_MESSAGE = "Choose both colours for custom colours."


def text(response):
    return response.content.decode()


def quiz_url(quiz, tail="branding"):
    return f"/admin/quizzes/{quiz.id}/{tail}"


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 10, 10)).save(buffer, "PNG")
    return SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")


def test_global_texts_change_the_landing(logged_in, client):
    response = logged_in.post(GLOBAL, {"name_cs": "Moje škola", "footer_cs": "Kontakt: škola"})
    assert response.status_code == 302
    html = text(client.get("/?lang=cs"))
    assert "Moje škola" in html and "Kontakt: škola" in html


def test_the_settings_page_shows_the_stored_texts(showing_all):
    showing_all.post(GLOBAL, {"name_cs": "Moje škola", "motto_en": "Hello"})
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'value="Moje škola"' in html and 'value="Hello"' in html


def test_a_quiz_overrides_one_field_and_removes_it(showing_all):
    quiz = make_quiz()
    branding.set_texts(None, "name", {"cs": "Škola"}, admin_id=ADMIN_ID)
    showing_all.post(quiz_url(quiz), {"motto_cs": "Hurá"})
    assert branding.resolve(quiz, "cs").motto == "Hurá"
    assert branding.resolve(quiz, "cs").name == "Škola"
    page = text(showing_all.get(quiz_url(quiz, "settings") + "?lang=en"))
    assert "Inherited from global settings" in page and "Remove override" in page
    showing_all.post(quiz_url(quiz), {"clear": "motto"})
    assert branding.resolve(quiz, "cs").sources["motto"] == "default"
    showing_all.post(quiz_url(quiz), {"motto_cs": "Zase", "name_cs": ""})
    showing_all.post(quiz_url(quiz), {"motto_cs": ""})
    assert branding.resolve(quiz, "cs").sources["motto"] == "default"


@pytest.fixture
def uploading(admin_user):
    client = Client()  # multipart, which the form client does not send
    client.force_login(admin_user)
    return client


def test_a_logo_is_uploaded_and_removed(uploading):
    assert uploading.post(GLOBAL, {"logo": png()}).status_code == 302
    assert branding.resolve(None, "cs").logo_url.startswith("/media/")
    assert uploading.post(GLOBAL, {"remove_logo": "on"}).status_code == 302
    assert branding.resolve(None, "cs").logo_url == "/assets/logo-mint-bar.svg"


def test_a_hero_logo_is_uploaded_and_removed_independently_of_the_logo(uploading):
    assert uploading.post(GLOBAL, {"hero_logo": png()}).status_code == 302
    result = branding.resolve(None, "cs")
    assert result.hero_logo_url.startswith("/media/")
    assert result.logo_url == "/assets/logo-mint-bar.svg"
    assert uploading.post(GLOBAL, {"remove_hero_logo": "on"}).status_code == 302
    assert branding.resolve(None, "cs").hero_logo_url == "/assets/logo-mint-hero-light.svg"


def test_a_refused_logo_shows_the_message_and_keeps_the_typed_fields(uploading):
    bad = SimpleUploadedFile("logo.png", b"not an image", content_type="image/png")
    response = uploading.post(GLOBAL, {"logo": bad, "name_cs": "Moje škola"})
    assert response.status_code == 200
    html = text(response)
    assert 'value="Moje škola"' in html and "logo.png" in html
    assert not BrandingConfiguration.objects.exists()


def test_a_refused_hero_logo_blames_the_hero_logo_field(uploading):
    bad = SimpleUploadedFile("hero.png", b"not an image", content_type="image/png")
    response = uploading.post(GLOBAL, {"hero_logo": bad})
    assert response.status_code == 200
    html = text(response)
    assert "hero.png" in html
    assert not BrandingConfiguration.objects.exists()


def test_a_footer_over_300_characters_is_refused(logged_in):
    response = logged_in.post(GLOBAL, {"footer_cs": "x" * 301})
    assert response.status_code == 200
    assert not BrandingConfiguration.objects.exists()


def test_a_name_over_80_characters_is_refused(logged_in):
    assert logged_in.post(GLOBAL, {"name_cs": "x" * 81}).status_code == 200


def test_custom_colours_save_with_the_palette(logged_in):
    data = {COLOR_PALETTE: CUSTOM_PALETTE, "main": "#AA2255", "accent": "#2255aa"}
    assert logged_in.post("/admin/settings", data).status_code == 302
    assert settings.resolve(COLOR_PALETTE) == CUSTOM_PALETTE
    assert branding.colours_of(None) == BrandColours("#aa2255", "#2255aa")
    assert branding.resolve(None, "cs").custom is not None


def test_a_very_light_colour_saves_with_the_notice_and_swatches(logged_in):
    data = {COLOR_PALETTE: CUSTOM_PALETTE, "main": "#ffff00", "accent": "#ffff00"}
    assert logged_in.post("/admin/settings", data).status_code == 302
    html = text(logged_in.get("/admin/settings?lang=en"))
    used = branding.resolve(None, "cs").custom
    assert used is not None and used.adjusted
    assert (
        "The chosen colours do not reach WCAG AA contrast, so they were adjusted. "
        "These colours are used:" in html
    )
    assert f'fill="{used.main}"' in html and f'fill="{used.accent}"' in html
    assert re.search(r"<input[^>]*type=\"color\"[^>]*name=\"main\"", html)


def test_no_notice_when_the_colours_are_fine(logged_in):
    data = {COLOR_PALETTE: CUSTOM_PALETTE, "main": "#1a3a5c", "accent": "#7a1f3d"}
    logged_in.post("/admin/settings", data)
    assert "do not reach WCAG AA" not in text(logged_in.get("/admin/settings?lang=en"))


def test_custom_without_colours_is_refused(logged_in):
    response = logged_in.post("/admin/settings?lang=en", {COLOR_PALETTE: CUSTOM_PALETTE})
    assert response.status_code == 200
    assert CUSTOM_MESSAGE in text(response)
    assert settings.resolve(COLOR_PALETTE) != CUSTOM_PALETTE


def test_custom_with_one_colour_is_refused(logged_in):
    data = {COLOR_PALETTE: CUSTOM_PALETTE, "main": "#aa2255"}
    assert logged_in.post("/admin/settings?lang=en", data).status_code == 200
    assert branding.colours_of(None) is None


def test_an_invalid_colour_is_refused(logged_in):
    data = {COLOR_PALETTE: CUSTOM_PALETTE, "main": "red; }", "accent": "#2255aa"}
    assert logged_in.post("/admin/settings", data).status_code == 200
    assert branding.colours_of(None) is None


def test_other_settings_without_custom_leave_the_colours_alone(logged_in):
    branding.set_colours(None, BrandColours("#aa2255", "#2255aa"), admin_id=ADMIN_ID)
    logged_in.post("/admin/settings", {COLOR_PALETTE: "blue_teal", "main": "#000000"})
    assert branding.colours_of(None) == BrandColours("#aa2255", "#2255aa")


def test_a_quiz_chooses_custom_colours_in_its_behaviour_form(logged_in):
    quiz = make_quiz()
    data = {
        "slug": quiz.slug,
        COLOR_PALETTE: CUSTOM_PALETTE,
        "main": "#aa2255",
        "accent": "#2255aa",
    }
    assert logged_in.post(quiz_url(quiz, "settings"), data).status_code == 302
    assert branding.colours_of(quiz) == BrandColours("#aa2255", "#2255aa")
    assert branding.resolve(quiz, "cs").custom is not None


def test_a_quiz_custom_without_colours_is_refused(logged_in):
    quiz = make_quiz()
    data = {"slug": quiz.slug, COLOR_PALETTE: CUSTOM_PALETTE}
    response = logged_in.post(quiz_url(quiz, "settings") + "?lang=en", data)
    assert response.status_code == 200 and CUSTOM_MESSAGE in text(response)


def test_a_quiz_inheriting_the_palette_needs_no_colours(logged_in):
    quiz = make_quiz()
    data = {"slug": quiz.slug, COLOR_PALETTE: "", "main": "#000000", "accent": "#000000"}
    assert logged_in.post(quiz_url(quiz, "settings"), data).status_code == 302
    assert branding.colours_of(quiz) is None


def test_the_quiz_page_shows_the_notice_for_its_own_colours(logged_in):
    quiz = make_quiz()
    data = {
        "slug": quiz.slug,
        COLOR_PALETTE: CUSTOM_PALETTE,
        "main": "#ffff00",
        "accent": "#ffff00",
    }
    logged_in.post(quiz_url(quiz, "settings"), data)
    html = text(logged_in.get(quiz_url(quiz, "settings") + "?lang=en"))
    assert "do not reach WCAG AA contrast" in html


def test_an_archived_quiz_refuses_the_form(logged_in):
    quiz = make_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    response = logged_in.post(quiz_url(quiz), {"name_cs": "Nové"})
    assert response.status_code == 409
    assert not BrandingConfiguration.objects.exists()


def test_a_non_admin_is_sent_to_the_login(client):
    quiz = make_quiz()
    assert client.post(GLOBAL, {"name_cs": "x"}).status_code == 302
    assert client.post(quiz_url(quiz), {"name_cs": "x"}).status_code == 302
    assert not BrandingConfiguration.objects.exists()


def test_branding_makes_no_draft_and_audits_field_names(logged_in):
    quiz = published_quiz()
    before = QuizRevision.objects.filter(quiz=quiz).count()
    logged_in.post(quiz_url(quiz), {"name_cs": "Tajné jméno"})
    assert QuizRevision.objects.filter(quiz=quiz).count() == before
    events = AuditEvent.objects.filter(action="branding.changed")
    assert events.count() == 1 and events[0].details_json == {"field": "name"}


def test_saving_unchanged_values_audits_nothing(logged_in):
    logged_in.post(GLOBAL, {"name_cs": "Škola"})
    logged_in.post(GLOBAL, {"name_cs": "Škola"})
    assert AuditEvent.objects.filter(action="branding.changed").count() == 1


def test_the_pages_script_text_is_escaped(showing_all):
    showing_all.post(GLOBAL, {"name_cs": "<script>x</script>"})
    html = text(showing_all.get("/admin/settings?lang=cs"))
    assert "<script>x</script>" not in html


def test_a_quiz_logo_is_uploaded_over_multipart(uploading):
    quiz = make_quiz()
    assert uploading.post(quiz_url(quiz), {"logo": png()}).status_code == 302
    assert branding.resolve(quiz, "cs").sources["logo"] == "quiz"
    assert branding.resolve(None, "cs").sources["logo"] == "default"


def test_save_is_the_default_submit_of_the_quiz_branding_form(showing_all):
    quiz = make_quiz()
    showing_all.post(quiz_url(quiz), {"motto_cs": "Hurá"})
    html = text(showing_all.get(quiz_url(quiz, "settings") + "?lang=en"))
    assert 'name="clear"' in html  # the removal exists, in forms of its own
    start = html.index('id="branding"')
    form = html[html.index("<form", start) : html.index("</form>", start)]
    assert 'name="clear"' not in form
    assert re.search(r'<button type="submit">Save</button>', form)
    # Enter posts the typed text without "clear": it is saved, not wiped
    showing_all.post(quiz_url(quiz), {"motto_cs": "Změněno"})
    assert branding.resolve(quiz, "cs").motto == "Změněno"


def test_a_theme_without_logo_and_colours_gets_no_such_fields(logged_in, monkeypatch):
    real = branding.theme()

    class Limited:
        def __getattr__(self, name):
            return getattr(real, name)

        def branding_fields(self):
            return frozenset({"name", "motto", "footer"})

    monkeypatch.setattr(branding, "theme", lambda: Limited())
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert 'name="logo"' not in html and 'name="remove_logo"' not in html
    assert 'name="main"' not in html and 'name="accent"' not in html
    assert 'name="name_cs"' in html


def colour_inputs(html):
    """The values a browser would submit for the two colour inputs of the page."""
    found = {}
    for name in ("main", "accent"):
        tag = re.search(rf"<input[^>]*name=\"{name}\"[^>]*>", html)
        assert tag, name
        value = re.search(r'value="(#[0-9a-f]{6})"', tag.group(0))
        assert value, f"{name} renders no value"
        found[name] = value.group(1)
    return found


def test_the_global_page_renders_the_default_colours(logged_in):
    shown = colour_inputs(text(logged_in.get("/admin/settings?lang=en")))
    assert shown == {"main": "#1769e0", "accent": "#ffb020"}


def test_a_browser_choosing_custom_without_touching_the_pickers_saves_what_is_shown(logged_in):
    shown = colour_inputs(text(logged_in.get("/admin/settings?lang=en")))
    data = {COLOR_PALETTE: CUSTOM_PALETTE, **shown}
    assert logged_in.post("/admin/settings", data).status_code == 302
    assert branding.colours_of(None) == BrandColours(shown["main"], shown["accent"])


def test_a_quiz_without_colours_shows_the_global_ones_and_saves_them(logged_in):
    branding.set_colours(None, BrandColours("#aa2255", "#2255aa"), admin_id=ADMIN_ID)
    quiz = make_quiz()
    url = quiz_url(quiz, "settings")
    shown = colour_inputs(text(logged_in.get(url + "?lang=en")))
    assert shown == {"main": "#aa2255", "accent": "#2255aa"}
    data = {"slug": quiz.slug, COLOR_PALETTE: CUSTOM_PALETTE, **shown}
    assert logged_in.post(url, data).status_code == 302
    assert branding.colours_of(quiz) == BrandColours("#aa2255", "#2255aa")


def test_a_quiz_without_any_colours_shows_the_default_ones(logged_in):
    quiz = make_quiz()
    shown = colour_inputs(text(logged_in.get(quiz_url(quiz, "settings") + "?lang=en")))
    assert shown == {"main": "#1769e0", "accent": "#ffb020"}


def test_a_quiz_logo_is_removed_by_its_checkbox(uploading):
    quiz = make_quiz()
    assert uploading.post(quiz_url(quiz), {"logo": png()}).status_code == 302
    assert branding.has_logo(quiz)
    assert uploading.post(quiz_url(quiz), {"remove_logo": "on"}).status_code == 302
    assert not branding.has_logo(quiz)


def test_contact_email_saves_shows_and_clears(showing_all, client):
    """AC-99."""
    showing_all.post(GLOBAL, {"contact_email": "info@example.org"})
    assert 'href="mailto:info@example.org"' in text(client.get("/"))
    assert 'value="info@example.org"' in text(showing_all.get("/admin/settings?lang=en"))
    quiz = make_quiz()
    showing_all.post(quiz_url(quiz), {"contact_email": "quiz@example.org"})
    assert branding.resolve(quiz, "cs").contact_email == "quiz@example.org"
    showing_all.post(quiz_url(quiz), {"clear": "contact_email"})
    assert branding.resolve(quiz, "cs").contact_email == "info@example.org"


def test_an_invalid_contact_email_is_refused(logged_in):
    """AC-99."""
    response = logged_in.post(GLOBAL, {"contact_email": "nope"})
    assert response.status_code == 200
    assert branding.resolve(None, "cs").contact_email == ""


def test_contact_help_differs_between_the_global_and_the_quiz_form(showing_all):
    """AC-99: the global form names the footer, the quiz form the creator fallback."""
    global_page = text(showing_all.get("/admin/settings?lang=en"))
    assert "footer of every page that sets no contact of its own." in global_page
    assert "the e-mail of the admin who created the quiz" not in global_page
    quiz_page = text(showing_all.get(quiz_url(make_quiz(), "settings") + "?lang=en"))
    assert "Empty: the e-mail of the admin who created the quiz." in quiz_page
    assert "of every page" not in quiz_page


def test_contact_help_is_translated(showing_all):
    html = text(showing_all.get("/admin/settings?lang=cs"))
    assert "Shown publicly" not in html
    assert "Zobrazuje se veřejně v patičce každé stránky, která nemá vlastní kontakt." in html


def test_a_quoted_contact_cannot_add_mailto_headers(logged_in, client):
    """AC-99: the address is quoted in the href."""
    address = '"a?bcc=x"@d.cz'
    assert logged_in.post(GLOBAL, {"contact_email": address}).status_code == 302
    footer = text(client.get("/?lang=en")).split('<footer class="site-footer">')[1]
    assert 'href="mailto:%22a%3Fbcc%3Dx%22@d.cz"' in footer
    assert 'mailto:"a?bcc' not in footer


ADDRESS = "https://logos.example/a.png"
OTHER_ADDRESS = "https://logos.example/b.png"


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 10, 10)).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def fetch(monkeypatch):
    fake = mock.Mock(side_effect=lambda *a, **k: png_bytes())
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


@pytest.fixture
def down(monkeypatch):
    fake = mock.Mock(side_effect=remote.RemoteRefused("down"))
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


def test_a_logo_address_is_fetched_and_removed(uploading, fetch):
    """AC-128: an address is fetched into a local copy and the logo is removed like an upload."""
    assert uploading.post(GLOBAL, {"logo_source": ADDRESS}).status_code == 302
    fetch.assert_called_once()
    assert branding.resolve(None, "cs").logo_url.startswith("/media/")
    assert branding.logo_source(None) == ADDRESS
    assert uploading.post(GLOBAL, {"remove_logo": "on"}).status_code == 302
    assert branding.resolve(None, "cs").logo_url == "/assets/logo-mint-bar.svg"


def test_an_unchanged_logo_address_is_not_fetched_again(uploading, fetch):
    uploading.post(GLOBAL, {"logo_source": ADDRESS})
    fetch.assert_called_once()
    fetch.reset_mock()
    assert (
        uploading.post(GLOBAL, {"logo_source": ADDRESS, "name_cs": "Moje škola"}).status_code == 302
    )
    fetch.assert_not_called()


def test_a_changed_logo_address_is_fetched_again(uploading, fetch):
    uploading.post(GLOBAL, {"logo_source": ADDRESS})
    fetch.reset_mock()
    assert uploading.post(GLOBAL, {"logo_source": OTHER_ADDRESS}).status_code == 302
    fetch.assert_called_once()
    assert branding.logo_source(None) == OTHER_ADDRESS


def test_an_empty_logo_address_keeps_the_stored_logo(uploading, fetch):
    uploading.post(GLOBAL, {"logo_source": ADDRESS})
    assert uploading.post(GLOBAL, {"logo_source": "", "name_cs": "Moje škola"}).status_code == 302
    assert branding.logo_source(None) == ADDRESS
    assert branding.has_logo(None)


def test_a_file_wins_over_a_logo_address(uploading, fetch):
    uploading.post(GLOBAL, {"logo": png(), "logo_source": ADDRESS})
    fetch.assert_not_called()
    assert branding.logo_source(None) is None
    assert branding.resolve(None, "cs").logo_url.startswith("/media/")


def test_removing_beats_a_resubmitted_address(uploading, fetch):
    uploading.post(GLOBAL, {"logo_source": ADDRESS})
    assert branding.has_logo(None)
    fetch.reset_mock()
    assert (
        uploading.post(GLOBAL, {"remove_logo": "on", "logo_source": OTHER_ADDRESS}).status_code
        == 302
    )
    fetch.assert_not_called()
    assert not branding.has_logo(None)


def test_a_malformed_logo_address_is_refused_and_nothing_else_saves(uploading, fetch):
    response = uploading.post(
        GLOBAL, {"logo_source": "ftp://logos.example/a.png", "name_cs": "Moje škola"}
    )
    assert response.status_code == 200
    html = text(response)
    assert 'value="Moje škola"' in html
    fetch.assert_not_called()
    assert not BrandingConfiguration.objects.exists()


def test_an_unreachable_logo_address_is_refused(uploading, down):
    response = uploading.post(GLOBAL, {"logo_source": ADDRESS, "name_cs": "Moje škola"})
    assert response.status_code == 200
    assert blamed(response, "logo_source", ADDRESS)
    assert not BrandingConfiguration.objects.exists()


def test_a_hero_logo_address_is_independent_of_the_logo(uploading, fetch):
    assert uploading.post(GLOBAL, {"hero_logo_source": ADDRESS}).status_code == 302
    result = branding.resolve(None, "cs")
    assert result.hero_logo_url.startswith("/media/")
    assert result.logo_url == "/assets/logo-mint-bar.svg"
    assert branding.hero_logo_source(None) == ADDRESS


def test_a_quiz_logo_address_overrides_the_global_one(uploading, fetch):
    quiz = make_quiz()
    assert uploading.post(quiz_url(quiz), {"logo_source": ADDRESS}).status_code == 302
    assert branding.resolve(quiz, "cs").logo_url.startswith("/media/")
    assert branding.resolve(None, "cs").logo_url == "/assets/logo-mint-bar.svg"


def test_a_refused_second_image_applies_nothing(uploading, fetch, down):
    bad = SimpleUploadedFile("hero.png", b"not an image", content_type="image/png")
    response = uploading.post(GLOBAL, {"logo": png(), "hero_logo": bad})
    assert response.status_code == 200
    assert not BrandingConfiguration.objects.exists()
    assert not MediaAsset.objects.exists()


def test_a_refused_address_leaves_the_other_logo_as_it_was(uploading, fetch):
    uploading.post(GLOBAL, {"logo_source": ADDRESS})
    before = branding.resolve(None, "cs").logo_url
    fetch.side_effect = remote.RemoteRefused("down")
    response = uploading.post(GLOBAL, {"logo": png(), "hero_logo_source": OTHER_ADDRESS})
    assert response.status_code == 200
    assert branding.resolve(None, "cs").logo_url == before
    assert not branding.has_hero_logo(None)
    assert MediaAsset.objects.count() == 1


def test_the_settings_page_shows_the_stored_address_and_the_fields(showing_all, fetch):
    showing_all.post(GLOBAL, {"logo_source": ADDRESS})
    html = text(showing_all.get("/admin/settings"))
    assert 'name="logo_source"' in html and f'value="{ADDRESS}"' in html
    assert 'name="hero_logo_source"' in html


def test_the_address_fields_are_translated_to_czech(showing_all):
    html = text(showing_all.get("/admin/settings?lang=cs"))
    assert "Nebo adresa loga" in html and "Nebo adresa loga úvodní stránky" in html
    assert "Účastníci adresu nikdy neuvidí" in html


def test_a_quiz_settings_page_offers_both_addresses_in_the_basic_view(logged_in):
    quiz = make_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    assert 'name="logo_source"' in html and 'name="hero_logo_source"' in html


def blamed(response, field, label):
    """The refusal is listed at that field and starts with what the admin gave."""
    return f'id="id_{field}_error"><li>{label}: ' in text(response)


@pytest.mark.parametrize(
    "address", ["http://logos.example/a.png", "https://user:pw@logos.example/a.png"]
)
def test_an_address_the_provider_refuses_is_blamed_on_its_field(uploading, fetch, address):
    response = uploading.post(GLOBAL, {"hero_logo_source": address, "name_cs": "Moje škola"})
    assert response.status_code == 200
    assert blamed(response, "hero_logo_source", address)
    assert 'value="Moje škola"' in text(response)
    fetch.assert_not_called()
    assert not BrandingConfiguration.objects.exists()


def test_an_address_over_the_length_limit_is_refused_by_the_form(uploading, fetch):
    response = uploading.post(GLOBAL, {"logo_source": "https://logos.example/" + "a" * 2000})
    assert response.status_code == 200
    fetch.assert_not_called()
    assert not BrandingConfiguration.objects.exists()


def test_an_unreachable_hero_logo_address_is_blamed_on_its_field(uploading, down):
    response = uploading.post(GLOBAL, {"hero_logo_source": ADDRESS})
    assert blamed(response, "hero_logo_source", ADDRESS)
    assert not blamed(response, "logo_source", ADDRESS)


def test_both_addresses_are_fetched_in_one_save(uploading, fetch):
    response = uploading.post(GLOBAL, {"logo_source": ADDRESS, "hero_logo_source": OTHER_ADDRESS})
    assert response.status_code == 302
    assert MediaAsset.objects.count() == 2
    assert branding.logo_source(None) == ADDRESS
    assert branding.hero_logo_source(None) == OTHER_ADDRESS


def test_a_quiz_does_not_fetch_its_own_unchanged_address_again(uploading, fetch):
    quiz = make_quiz()
    uploading.post(quiz_url(quiz), {"logo_source": ADDRESS})
    assert branding.logo_source(quiz) == ADDRESS
    fetch.reset_mock()
    assert uploading.post(quiz_url(quiz), {"logo_source": ADDRESS}).status_code == 302
    fetch.assert_not_called()


def test_a_quiz_fetches_an_address_stored_only_globally_into_its_own_copy(uploading, fetch):
    quiz = make_quiz()
    uploading.post(GLOBAL, {"logo_source": ADDRESS})
    uploading.post(quiz_url(quiz), {"logo_source": ADDRESS})
    assert fetch.call_count == 2
    assert MediaAsset.objects.count() == 2
    uploading.post(quiz_url(quiz), {"remove_logo": "on"})
    assert MediaAsset.objects.count() == 1
    assert branding.resolve(quiz, "cs").logo_url == branding.resolve(None, "cs").logo_url


def test_a_failure_while_saving_the_second_image_changes_neither(uploading, fetch, monkeypatch):
    real = branding._save

    def fails_on_the_second(quiz, field, admin_id, **changes):
        if field == "hero_logo":
            raise RuntimeError("database")
        return real(quiz, field, admin_id, **changes)

    monkeypatch.setattr(branding, "_save", fails_on_the_second)
    uploading.raise_request_exception = False
    response = uploading.post(GLOBAL, {"logo_source": ADDRESS, "hero_logo_source": OTHER_ADDRESS})
    assert response.status_code == 500
    assert not BrandingConfiguration.objects.exists()
    assert not MediaAsset.objects.exists()


def test_global_settings_page_previews_the_builtin_logo(showing_all):
    """AC-148."""
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'class="logo-preview"' in html and "/assets/logo-mint-bar.svg" in html
    assert "Built-in logo (mint)" in html


def test_quiz_settings_page_previews_the_builtin_logo(showing_all):
    quiz = make_quiz()
    html = text(showing_all.get(quiz_url(quiz, "settings") + "?lang=en"))
    assert 'class="logo-preview"' in html and "Built-in logo (mint)" in html


def test_preview_names_a_custom_logo_instead_of_the_builtin_one(showing_all):
    branding.set_logo(None, png().read(), admin_id=ADMIN_ID)
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'class="logo-preview"' in html and "/assets/logo-mint-bar.svg" not in html
    assert "A custom logo is used for the bar." in html


def test_the_global_settings_offer_the_large_logo_switch(showing_all):
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'name="show_hero_logo"' in html


def test_a_quiz_does_not_offer_the_large_logo_switch(showing_all):
    html = text(showing_all.get(quiz_url(make_quiz(), "settings") + "?lang=en"))
    assert 'name="show_hero_logo"' not in html


def test_saving_the_switch_hides_the_large_logo(showing_all):
    """AC-149."""
    showing_all.post("/admin/settings", {"show_hero_logo": "off"})
    assert branding.resolve(None, "cs").show_hero_logo is False


def test_a_set_logo_is_removed_by_a_button(showing_all):
    """AC-150."""
    branding.set_logo(None, png().read(), admin_id=ADMIN_ID)
    branding.set_hero_logo(None, png().read(), admin_id=ADMIN_ID)
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'name="clear" value="logo"' in html and 'name="clear" value="hero_logo"' in html
    assert 'name="remove_logo"' not in html and 'name="remove_hero_logo"' not in html
    assert 'aria-label="Remove: Logo"' in html
    assert 'aria-label="Remove: Landing page logo"' in html
    showing_all.post(GLOBAL, {"clear": "logo"})
    assert branding.resolve(None, "cs").sources["logo"] == "default"
    assert branding.resolve(None, "cs").sources["hero_logo"] == "global"


def test_there_is_no_removal_button_without_a_set_logo(showing_all):
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'name="clear" value="logo"' not in html
    assert 'name="clear" value="hero_logo"' not in html
    assert 'aria-label="Remove:' not in html


def test_a_quiz_with_its_own_logo_is_cleared_by_a_button(showing_all):
    quiz = make_quiz()
    branding.set_logo(quiz, png().read(), admin_id=ADMIN_ID)
    html = text(showing_all.get(quiz_url(quiz, "settings") + "?lang=en"))
    assert 'name="clear" value="logo"' in html and 'name="remove_logo"' not in html


def named_png(name):
    return SimpleUploadedFile(name, png().read(), content_type="image/png")


def test_the_logo_row_shows_a_thumbnail_the_file_name_and_a_small_button(uploading, showing_all):
    """AC-152."""
    uploading.post(GLOBAL, {"logo": named_png("firma <b>.png")})
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'class="logo-row"' in html
    assert re.search(r'<p class="logo-row"><img src="/media/[^"]+" alt="" width="24"', html)
    assert "firma &lt;b&gt;.png" in html and "firma <b>.png" not in html
    # The accessible name starts with the visible word.
    assert re.search(r'aria-label="Remove: firma &lt;b&gt;\.png"', html)
    assert ">Remove</button>" in html


def test_the_logo_row_of_a_logo_without_a_name_shows_only_the_thumbnail(showing_all):
    branding.set_images(
        None,
        {"hero_logo": branding.Upload(png().read(), "")},
        admin_id=ADMIN_ID,
    )
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'class="logo-row"' in html and 'class="logo-name"' not in html  # no name, no label


def test_there_is_no_logo_row_without_an_own_logo(showing_all):
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'class="logo-row"' not in html


def test_a_quiz_shows_a_logo_row_for_its_own_logo_only(uploading, showing_all):
    quiz = make_quiz()
    branding.set_hero_logo(None, png().read(), admin_id=ADMIN_ID)  # inherited
    uploading.post(quiz_url(quiz), {"logo": named_png("kviz.png")})
    html = text(showing_all.get(quiz_url(quiz, "settings") + "?lang=en"))
    assert html.count('class="logo-row"') == 1 and "kviz.png" in html


def test_the_removal_button_without_a_label_still_names_its_logo(showing_all):
    branding.set_logo(None, png().read(), admin_id=ADMIN_ID)  # stored with no file name
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'aria-label="Remove: Logo"' in html


def test_a_failing_second_text_save_leaves_the_first_unchanged(logged_in):
    real = branding.set_texts
    calls = []

    def second_fails(*args, **kwargs):
        calls.append(args[1])
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    with mock.patch.object(branding, "set_texts", side_effect=second_fails):
        with pytest.raises(RuntimeError):
            logged_in.post(GLOBAL, {"name_cs": "Moje škola", "motto_cs": "Heslo"})
    assert len(calls) == 2
    assert branding.texts_of(None).get("name", {}) == {}
    assert not BrandingConfiguration.objects.exists()


def test_a_text_failure_after_an_image_change_keeps_the_image_and_its_file(uploading):
    with mock.patch.object(branding, "set_texts", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            uploading.post(GLOBAL, {"logo": png(), "name_cs": "Moje škola"})
    row = BrandingConfiguration.objects.get()
    asset_id = row.assets_json["logo"]["asset"]
    assert branding.media().exists(asset_id)
    assert branding.resolve(None, "cs").logo_url.startswith("/media/")
    assert not row.texts_json

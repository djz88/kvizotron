"""Public pages: menu, information pages, descriptions and colours (FR-51, FR-52, FR-53)."""

import pytest

from app.domain import settings
from app.domain.models import QuizRevision
from tests.domain.helpers import open_quiz_run

pytestmark = pytest.mark.django_db
INFO_PAGES = ["/how-it-works", "/about", "/privacy"]


def text(response):
    return response.content.decode()


@pytest.mark.parametrize("path", INFO_PAGES)
@pytest.mark.parametrize("lang", ["cs", "en", "uk"])
def test_information_page_exists_in_every_language(client, path, lang):
    response = client.get(f"{path}?lang={lang}")
    assert response.status_code == 200
    assert f'<html lang="{lang}"' in text(response)


def test_privacy_page_says_what_it_covers(client):
    html = text(client.get("/privacy?lang=en"))
    assert "current version" in html and "register" in html


@pytest.mark.parametrize("path", ["/", "/about", "/q/kviz"])
def test_menu_links_are_on_public_pages(client, path):
    open_quiz_run()
    html = text(client.get(path))
    for target in INFO_PAGES:
        assert f'href="{target}?lang=' in html


def test_menu_keeps_the_chosen_language(client):
    assert 'href="/about?lang=uk"' in text(client.get("/?lang=uk"))


def test_home_shows_slogan_motto_and_quiz_description(client):
    open_quiz_run(description={"cs": "Krátký popis"})
    html = text(client.get("/?lang=cs"))
    assert "Zapni mozek. Spusť Kvízotron." in html
    assert 'class="hero"' in html
    assert "Krátký popis" in html


def test_quiz_page_shows_title_description_and_start(client):
    run = open_quiz_run(description={"cs": "Krátký popis"})
    html = text(client.get("/q/kviz"))
    assert "Název cs" in html and "Krátký popis" in html
    assert f'action="/r/{run.id}/start"' in html


def test_old_revision_without_description_still_shows_its_page(client):
    run = open_quiz_run()
    revision = run.current_revision
    snapshot = dict(revision.snapshot_json)
    del snapshot["description"]
    QuizRevision.objects.filter(pk=revision.pk).update(snapshot_json=snapshot)
    assert client.get("/q/kviz").status_code == 200
    assert client.get("/").status_code == 200


def test_one_language_quiz_offers_no_other_language(client):
    open_quiz_run(locales=("cs",))
    html = text(client.get("/q/kviz"))
    assert "flag-cs.svg" in html
    assert "?lang=en" not in html and "?lang=uk" not in html
    assert 'class="dropdown language"' not in html


def test_two_language_quiz_links_only_its_languages(client):
    open_quiz_run(locales=("cs", "uk"))
    html = text(client.get("/q/kviz"))
    assert 'class="dropdown language"' in html
    assert "?lang=uk" in html and "flag-en.svg" not in html


def test_active_language_is_marked(client):
    open_quiz_run(locales=("cs", "uk"))
    html = text(client.get("/q/kviz?lang=uk"))
    summary = html.split('class="dropdown language"')[1].split("</summary>")[0]
    assert "flag-uk.svg" in summary


def test_quiz_palette_applies_only_to_its_public_pages(client):
    run = open_quiz_run()
    settings.set_override(settings.COLOR_PALETTE, run.quiz, "indigo_pink", admin_id=None)
    assert 'data-palette="indigo_pink"' in text(client.get("/q/kviz"))
    assert 'data-palette="blue_teal"' in text(client.get("/"))
    assert 'data-palette="blue_teal"' in text(client.get("/about"))


def test_palette_applies_to_a_page_drawn_without_javascript(client):
    run = open_quiz_run()
    settings.set_override(settings.COLOR_PALETTE, run.quiz, "indigo_pink", admin_id=None)
    html = text(client.post(f"/r/{run.id}/start", {"lang": "cs"}))
    assert 'data-palette="indigo_pink"' in html


def test_deleting_override_returns_to_global(client):
    run = open_quiz_run()
    settings.set_override(settings.COLOR_PALETTE, run.quiz, "indigo_pink", admin_id=None)
    settings.set_override(settings.COLOR_PALETTE, run.quiz, None, admin_id=None)
    assert 'data-palette="blue_teal"' in text(client.get("/q/kviz"))


def test_flag_assets_are_served_as_svg(client):
    for code in ("cs", "en", "uk"):
        response = client.get(f"/assets/flag-{code}.svg")
        assert response.status_code == 200
        assert response["Content-Type"] == "image/svg+xml"


def test_navigation_script_is_served_and_loaded(client):
    assert client.get("/assets/nav.js").status_code == 200
    assert "/assets/nav.js" in text(client.get("/"))


def test_playing_page_has_no_large_heading(client):
    run = open_quiz_run()
    html = text(client.post(f"/r/{run.id}/start", {"lang": "cs"}))
    assert 'class="hero"' not in html


def test_starting_replaces_the_heading_too(client):
    open_quiz_run()
    html = text(client.get("/q/kviz"))
    assert html.index('id="play"') < html.index('class="hero"') < html.index("</form>")

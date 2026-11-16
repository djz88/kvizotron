import hashlib

import pytest
from django.template.loader import render_to_string
from django.utils import translation

from app.contracts import BRANDING_FIELDS
from app.domain import branding
from app.plugins.theme_default.plugin import ASSETS, DefaultTheme
from tests.contracts.theme import ThemeContract


class TestDefaultTheme(ThemeContract):
    plugin = DefaultTheme()


def test_default_theme_offers_the_five_presets_and_every_branding_field():
    theme = DefaultTheme()
    assert list(theme.palettes()) == [
        "blue_teal",
        "indigo_pink",
        "violet_white",
        "green_blue",
        "red_plum",
    ]
    assert theme.branding_fields() == frozenset(BRANDING_FIELDS)


@pytest.mark.django_db
def test_stylesheets_are_served(client):
    urls = DefaultTheme().stylesheet_urls()
    assert len(urls) == 2
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/css")
        assert "max-age" in response["Cache-Control"]


def test_stylesheet_addresses_change_with_their_content():
    """A browser keeps a stylesheet for an hour; a new version must not wait for that."""
    for url in DefaultTheme().stylesheet_urls():
        path, version = url.split("?v=")
        content = (ASSETS / path.rsplit("/", 1)[1]).read_bytes()
        assert version == hashlib.sha256(content).hexdigest()[:12]


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["../plugin.py", "secret.css", "pico.LICENSE.md"])
def test_other_files_are_not_served(client, name):
    assert client.get(f"/m/theme.default/{name}").status_code == 404


@pytest.mark.django_db
def test_layout_is_in_the_active_language():
    with translation.override("cs"):
        html = render_to_string(
            "theme_default/layout.html",
            {"theme": DefaultTheme(), "locale": "cs", "branding": branding.resolve(None, "cs")},
        )
    assert '<html lang="cs"' in html
    assert "Kvízotron" in html
    assert "style=" not in html


@pytest.mark.django_db
def test_layout_has_skip_link():
    context = {"theme": DefaultTheme(), "locale": "en", "branding": branding.resolve(None, "en")}
    html = render_to_string("theme_default/layout.html", context)
    assert 'href="#content"' in html and 'id="content"' in html

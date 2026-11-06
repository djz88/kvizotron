import pytest
from django.template.loader import render_to_string
from django.utils import translation

from app.plugins.theme_default.plugin import DefaultTheme
from tests.contracts.theme import ThemeContract


class TestDefaultTheme(ThemeContract):
    plugin = DefaultTheme()


@pytest.mark.django_db
def test_stylesheets_are_served(client):
    urls = DefaultTheme().stylesheet_urls()
    assert len(urls) == 2
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/css")
        assert "max-age" in response["Cache-Control"]


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["../plugin.py", "secret.css", "pico.LICENSE.md"])
def test_other_files_are_not_served(client, name):
    assert client.get(f"/m/theme.default/{name}").status_code == 404


def test_layout_is_in_the_active_language():
    with translation.override("cs"):
        html = render_to_string(
            "theme_default/layout.html", {"theme": DefaultTheme(), "locale": "cs"}
        )
    assert '<html lang="cs"' in html
    assert "Kvízotron" in html
    assert "Zapni mozek. Spusť Kvízotron." in html
    assert "style=" not in html


def test_layout_has_skip_link():
    html = render_to_string("theme_default/layout.html", {"theme": DefaultTheme(), "locale": "en"})
    assert 'href="#content"' in html and 'id="content"' in html

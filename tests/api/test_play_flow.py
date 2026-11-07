import re
from unittest import mock

import pytest

from app.domain import settings
from app.kernel import registry
from tests.domain.helpers import open_quiz_run

pytestmark = pytest.mark.django_db
HTMX = {"HX-Request": "true"}


def start_page(client, run, lang="cs"):
    response = client.post(f"/r/{run.id}/start", {"lang": lang}, headers=HTMX)
    assert response.status_code == 200
    return response.content.decode()


@pytest.fixture
def run():
    return open_quiz_run(questions=3)


def test_page_carries_the_mode(client, run):
    assert "data-flow-step" not in start_page(client, run)
    settings.set_override(settings.NAVIGATION_MODE, run.quiz, "step_back", admin_id=None)
    html = start_page(client, run)
    assert "data-flow-step" in html
    assert "data-flow-back" in html
    settings.set_override(settings.NAVIGATION_MODE, run.quiz, "step_no_back", admin_id=None)
    html = start_page(client, run)
    assert "data-flow-step" in html
    assert "data-flow-back" not in html


def test_controls_start_hidden_so_the_page_works_without_script(client, run):
    settings.set_override(settings.NAVIGATION_MODE, run.quiz, "step_back", admin_id=None)
    html = start_page(client, run)
    sections = re.findall(r'<section class="flow-question"[^>]*>', html)
    assert len(sections) == 3
    assert not any("hidden" in section for section in sections)
    assert re.search(r'class="flow-nav"[^>]* hidden', html)
    assert re.search(r'class="flow-progress"[^>]* hidden', html)
    assert 'id="play-submit"' in html


def test_flow_script_is_served_and_included(client, run):
    response = client.post(f"/r/{run.id}/start")
    assert "/assets/flow.js" in response.content.decode()
    assert client.get("/assets/flow.js").status_code == 200


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("cs", "Otázka {current} z {total}"),
        ("en", "Question {current} of {total}"),
        ("uk", "Питання {current} з {total}"),
    ],
)
def test_progress_texts_are_translated(client, lang, text):
    run = open_quiz_run(locales=("cs", "en", "uk"))
    assert text in start_page(client, run, lang)


def test_unavailable_flow_plugin_gives_the_one_page_form(client, run):
    settings.set_override(settings.NAVIGATION_MODE, run.quiz, "step_back", admin_id=None)
    real = registry.get

    def without_flow(capability, *args, **kwargs):
        if capability == "quiz_flow":
            raise registry.UnknownPort("gone")
        return real(capability, *args, **kwargs)

    with mock.patch.object(registry, "get", side_effect=without_flow):
        html = start_page(client, run)
    assert "data-flow-step" not in html
    assert 'id="play-submit"' in html


def test_result_shows_from_its_top_after_a_long_form(client, run):
    """The list of answers can be long, and the submit button sits at the bottom of the form."""
    html = start_page(client, run)
    assert re.search(r'<form[^>]*hx-swap="innerHTML show:window:top"', html)


def test_check_button_does_not_inherit_the_jump_to_the_top(client, run):
    settings.set_override(settings.NAVIGATION_MODE, run.quiz, "step_back", admin_id=None)
    settings.set_override(settings.REVEAL_MOMENT, run.quiz, "after_each", admin_id=None)
    html = start_page(client, run)
    assert re.search(r'<button[^>]*data-flow-check-button[^>]*hx-swap="innerHTML"', html)

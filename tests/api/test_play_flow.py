import re
from unittest import mock

import pytest

from app.domain import settings
from app.kernel import registry
from tests.domain.helpers import keep, open_quiz_run

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
    keep(run, settings.NAVIGATION_MODE, "all_at_once")
    assert "data-flow-step" not in start_page(client, run)
    keep(run, settings.NAVIGATION_MODE, "step_back")
    html = start_page(client, run)
    assert "data-flow-step" in html
    assert "data-flow-back" in html
    keep(run, settings.NAVIGATION_MODE, "step_no_back")
    html = start_page(client, run)
    assert "data-flow-step" in html
    assert "data-flow-back" not in html


def test_controls_start_hidden_so_the_page_works_without_script(client, run):
    keep(run, settings.NAVIGATION_MODE, "step_back")
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
        ("cs", "Otázky {first}–{last} z {total}"),
        ("en", "Questions {first}–{last} of {total}"),
        ("uk", "Питання {first}–{last} з {total}"),
    ],
)
def test_progress_texts_are_translated(client, lang, text):
    run = open_quiz_run(locales=("cs", "en", "uk"))
    response = client.post(f"/r/{run.id}/start?lang={lang}", {"lang": lang}, headers=HTMX)
    assert text in response.content.decode()


def test_unavailable_flow_plugin_gives_the_one_page_form(client, run):
    keep(run, settings.NAVIGATION_MODE, "step_back")
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
    keep(run, settings.NAVIGATION_MODE, "step_back")
    keep(run, settings.REVEAL_MOMENT, "after_each")
    html = start_page(client, run)
    assert re.search(r'<button[^>]*data-flow-check-button[^>]*hx-swap="innerHTML"', html)


def test_pages_mode_carries_the_page_size(client, run):
    """AC-88: pages step by N questions and allow going back."""
    keep(run, settings.NAVIGATION_MODE, "pages")
    keep(run, settings.PAGE_SIZE, "2")
    html = start_page(client, run, "uk")
    assert "data-flow-step" in html and "data-flow-back" in html
    assert 'data-flow-page="2"' in html
    assert "data-progress-page=" in html


def test_page_size_is_fixed_when_the_attempt_starts(client, run):
    keep(run, settings.NAVIGATION_MODE, "pages")
    keep(run, settings.PAGE_SIZE, "3")
    html = start_page(client, run)
    token = re.search(r'name="attempt_token" value="([^"]+)"', html).group(1)
    attempt_id = re.search(r'data-attempt="([^"]+)"', html).group(1)
    keep(run, settings.PAGE_SIZE, "7")
    resumed = client.post(
        f"/r/{run.id}/resume", {"attempt_id": attempt_id, "attempt_token": token}, headers=HTMX
    )
    assert 'data-flow-page="3"' in resumed.content.decode()


def test_one_question_steps_carry_page_one(client, run):
    keep(run, settings.NAVIGATION_MODE, "step_back")
    assert 'data-flow-page="1"' in start_page(client, run)


def test_flow_script_moves_focus_after_start():
    """The script is read as text (TD-039); the focus itself is checked in a browser walkthrough."""
    from pathlib import Path

    code = Path("app/api/assets/flow.js").read_text(encoding="utf-8")
    assert "function focusFirstStep" in code
    assert "form[data-start-form], form[data-resume-form]" in code
    assert "requestConfig" in code
    # A restored attempt moves to its step in the same swap, so the focus waits for it.
    assert "setTimeout(focusFirstStep" in code


@pytest.mark.parametrize("mode", ["all_at_once", "step_back", "step_no_back"])
def test_every_question_section_can_take_focus(client, run, mode):
    keep(run, settings.NAVIGATION_MODE, mode)
    sections = re.findall(r'<section class="flow-question"[^>]*>', start_page(client, run))
    assert len(sections) == 3
    assert all('tabindex="-1"' in section for section in sections)


def test_start_and_resume_forms_are_marked_for_the_focus_hook(client, run):
    html = client.get(f"/q/{run.quiz.slug}?lang=en").content.decode()
    assert "data-start-form" in html
    assert "data-resume-form" in html


def test_questions_form_carries_the_unanswered_text(client, run):
    html = start_page(client, run, "cs")
    assert "data-unanswered-confirm=" in html
    assert "Otázky bez odpovědi: {count}. Přesto odeslat?" in html


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("en", "Questions without an answer: {count}. Submit anyway?"),
        ("uk", "Питання без відповіді"),
    ],
)
def test_unanswered_text_is_translated(client, lang, text):
    run = open_quiz_run(questions=3, locales=("cs", "en", "uk"))
    response = client.post(f"/r/{run.id}/start", {"lang": lang}, headers=HTMX)
    assert text in response.content.decode()


def test_flow_script_asks_before_an_incomplete_submission():
    from pathlib import Path

    code = Path("app/api/assets/flow.js").read_text(encoding="utf-8")
    assert '"htmx:confirm"' in code
    assert "unansweredConfirm" in code
    assert "issueRequest" in code
    assert "window.confirm" in code
    # Plain form posts (no script) never meet the dialog; a photo already stored counts as answered.
    assert "[data-photo-sent]" in code


def test_automatic_submission_does_not_ask():
    """The countdown flags its send with auto_submit; the confirm hook lets that through."""
    from pathlib import Path

    flow = Path("app/api/assets/flow.js").read_text(encoding="utf-8")
    countdown = Path("app/api/assets/countdown.js").read_text(encoding="utf-8")
    assert 'marker.name = "auto_submit"' in countdown
    assert '[name="auto_submit"]' in flow
    # The skip comes before the count, so no dialog can open for the automatic send.
    assert flow.index('[name="auto_submit"]') < flow.index("window.confirm")

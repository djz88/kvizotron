import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from app.domain import authoring, settings
from app.domain.models import Attempt
from tests.api.test_play import Play
from tests.api.test_play_reveal import after_close_run, make_run
from tests.domain.helpers import ADMIN_ID, OPTION_A, OPTION_B

pytestmark = pytest.mark.django_db
HTMX = {"HX-Request": "true"}


def check(client, play, question_id=None, option=OPTION_A):
    question_id = question_id or play.question_ids[0]
    action = play.action.replace("/submit", "/check")
    fields = {
        "attempt_token": play.fields["attempt_token"],
        "lang": play.fields["lang"],
        "check_question": question_id,
    }
    if option:
        fields[f"{question_id}:options[]"] = option
    return client.post(action, fields, headers=HTMX)


@pytest.fixture
def play(client):
    return Play(client, make_run("after_each", "explanations", explanation={"cs": "Protože"}))


def test_check_returns_the_reveal(client, play):
    """AC-18: in a run with no scoreboard or rewards the participant sees the solution."""
    html = check(client, play).content.decode()
    assert "Správně" in html
    assert "reveal-correct" in html
    assert "Protože" in html


def test_check_of_a_wrong_answer(client, play):
    html = check(client, play, option=OPTION_B).content.decode()
    assert "Špatně" in html
    assert "reveal-theirs" in html


def test_check_follows_the_level(client):
    play = Play(client, make_run("after_each", "verdict", explanation={"cs": "Protože"}))
    html = check(client, play).content.decode()
    assert "Správně" in html
    assert "reveal-correct" not in html
    assert "Protože" not in html


@pytest.mark.parametrize("moment", ["at_end", "never"])
def test_check_refuses_when_moment_does_not_allow_it(client, moment):
    play = Play(client, make_run(moment, "explanations", explanation={"cs": "Protože"}))
    response = check(client, play)
    assert response.status_code == 403
    assert "Protože" not in response.content.decode()
    assert "reveal-correct" not in response.content.decode()


def test_check_refuses_after_close(client):
    play = Play(client, after_close_run())
    response = check(client, play)
    assert response.status_code == 403
    assert "reveal-correct" not in response.content.decode()


def test_check_refuses_a_question_not_given(client, play):
    assert check(client, play, question_id="unknown").status_code == 403


def test_check_refuses_after_submission(client, play):
    assert play.submit().status_code == 200
    assert check(client, play).status_code == 409


def test_check_refuses_a_bad_token(client, play):
    play.fields["attempt_token"] = "forged"
    assert check(client, play).status_code == 403


def test_check_refuses_after_the_run_closed(client, play):
    authoring.close_run(play.run, admin_id=ADMIN_ID)
    assert check(client, play).status_code == 409


def test_check_refuses_a_malformed_answer(client, play):
    assert check(client, play, option="forged").status_code == 400


def test_check_writes_nothing(client, play):
    before = Attempt.objects.values().get()
    with CaptureQueriesContext(connection) as queries:
        assert check(client, play).status_code == 200
    written = [q["sql"] for q in queries if re.match(r"\s*(INSERT|UPDATE|DELETE)", q["sql"], re.I)]
    assert written == []
    assert Attempt.objects.values().get() == before


def test_check_uses_the_frozen_setting(client, play):
    settings.set_override(settings.REVEAL_MOMENT, play.run.quiz, "never", admin_id=None)
    assert check(client, play).status_code == 200


def test_get_is_refused(client, play):
    assert client.get(play.action.replace("/submit", "/check")).status_code == 405


def test_start_page_contains_no_correct_answer_or_explanation(client, play):
    html = play.start_response.content.decode()
    assert "Protože" not in html
    assert "reveal-correct" not in html
    assert '"correct"' not in html


def test_check_button_only_with_after_each(client):
    html = Play(client, make_run("after_each")).start_response.content.decode()
    assert "data-flow-check-button" in html
    assert re.search(r"<button[^>]*data-flow-check-button[^>]* hidden", html)


def test_no_check_button_when_answers_show_at_the_end(client):
    html = Play(client, make_run("at_end")).start_response.content.decode()
    assert "data-flow-check-button" not in html

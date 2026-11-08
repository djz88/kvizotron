"""AC-75: a test link has the name fields and no repeat limit, and its people go with it."""

import pytest

from app.domain import attempts, authoring, participants, run_links, settings
from app.domain.models import Attempt, Participant, QuizRun
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def field(html, name):
    return html.split(f'name="{name}" value="')[1].split('"')[0]


def a_link():
    quiz = published_quiz(locales=("cs", "en"))
    settings.set_override("ask_name", quiz, "required", admin_id=ADMIN_ID)
    settings.set_override("ask_email", quiz, "optional", admin_id=ADMIN_ID)
    settings.set_override("repeat_attempts", quiz, "forbid", admin_id=ADMIN_ID)
    revision = authoring.latest_published(quiz)
    return run_links.create(quiz, revision, expires_at=None, admin_id=ADMIN_ID)


def play(client, link, **fields):
    html = text(client.post(f"/r/{link.run_id}/start", {"lang": "en"}))
    attempt_id = html.split("/a/")[1].split("/")[0]
    response = client.post(
        f"/a/{attempt_id}/submit",
        {
            "attempt_token": field(html, "attempt_token"),
            "submission_key": field(html, "submission_key"),
            "lang": "en",
            **fields,
        },
    )
    return html, response


def test_test_link_has_fields_but_no_repeat_limit():
    link = a_link()
    client = FormClient()
    for _ in range(2):
        html, response = play(client, link, participant_name="Tester")
        assert 'name="participant_name"' in html
        assert 'name="participant_email"' in html
        assert response.status_code == 200
    run = QuizRun.all_kinds.get(pk=link.run_id)
    assert Attempt.objects.filter(run=run, status=Attempt.Status.SUBMITTED).count() == 2
    assert participants.rules_of(run)["repeat_attempts"] == "allow"
    assert Participant.objects.get().display_name == "Tester"


def test_deleting_test_link_removes_participants():
    link = a_link()
    play(FormClient(), link, participant_name="Tester", participant_email="t@x.cz")
    assert Participant.objects.count() == 1
    run_links.delete(link, admin_id=ADMIN_ID)
    assert Participant.objects.count() == 0
    assert Attempt.objects.count() == 0


def test_deleting_attempts_of_a_test_link_removes_participants():
    link = a_link()
    play(FormClient(), link, participant_name="Tester")
    run_links.delete_attempts(link, admin_id=ADMIN_ID)
    assert Participant.objects.count() == 0
    assert Attempt.objects.count() == 0
    started = attempts.start(link.run)
    assert started.attempt.status == Attempt.Status.IN_PROGRESS

"""AC-70, AC-71: the cookie that identifies a browser exists only when a run needs it."""

import pytest

from app.domain import authoring, participants
from app.domain.models import Attempt, Participant
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db


def a_run(**rules):
    return authoring.open_run(published_quiz(), admin_id=ADMIN_ID, rules=rules or None)


def start(client, run):
    return client.post(f"/r/{run.id}/start", {"lang": "cs"})


def field(html, name):
    return html.split(f'name="{name}" value="')[1].split('"')[0]


def submit(client, run, response):
    html = response.content.decode()
    attempt_id = html.split("/a/")[1].split("/")[0]
    return client.post(
        f"/a/{attempt_id}/submit",
        {
            "attempt_token": field(html, "attempt_token"),
            "submission_key": field(html, "submission_key"),
            "lang": "cs",
        },
    )


def test_allow_never_sets_cookie():
    run = a_run()
    response = start(FormClient(), run)
    assert response.status_code == 200
    assert not [name for name in response.cookies if name.startswith(participants.COOKIE_PREFIX)]
    assert Participant.objects.count() == 0


def test_forbid_sets_httponly_lax_cookie():
    run = a_run(repeat_attempts="forbid")
    response = start(FormClient(), run)
    cookie = response.cookies[participants.cookie_name(run)]
    assert cookie["httponly"] and cookie["samesite"] == "Lax" and cookie["path"] == "/"
    assert int(cookie["max-age"]) == 30 * 24 * 3600
    attempt = Attempt.objects.get()
    assert attempt.participant is not None
    assert attempt.participant.anonymous_key_hash != cookie.value


def test_second_start_in_same_browser_is_refused_after_submit_with_result_link():
    run = a_run(repeat_attempts="forbid")
    browser = FormClient()
    done = submit(browser, run, start(browser, run))
    assert done.status_code == 200
    refused = start(browser, run)
    assert refused.status_code == 409
    html = refused.content.decode()
    assert "Tento běh už jste v tomto prohlížeči hráli." in html
    assert "Platí jeden pokus na prohlížeč." in html
    assert Attempt.objects.count() == 1


def test_other_browser_is_a_new_participant():
    run = a_run(repeat_attempts="forbid")
    submit(FormClient(), run, start(FormClient(), run))
    assert start(FormClient(), run).status_code == 200
    assert Participant.objects.count() == 2


def test_closed_attempt_cannot_be_submitted_over_http():
    run = a_run(repeat_attempts="forbid", unfinished_attempt="submitted")
    browser = FormClient()
    first = start(browser, run)
    start(browser, run)
    assert submit(browser, run, first).status_code == 409


def test_abandoned_attempt_cannot_switch_over_http():
    from tests.domain.helpers import OPTION_B, add_question

    run = a_run(repeat_attempts="forbid", unfinished_attempt="submitted")
    browser = FormClient()
    first = start(browser, run).content.decode()
    start(browser, run)
    first_id = run.current_revision.snapshot_json["questions"][0]["id"]
    add_question(run.quiz, OPTION_B, question_id=first_id)
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)
    attempt_id = first.split("/a/")[1].split("/")[0]
    response = browser.post(
        f"/a/{attempt_id}/switch",
        {"attempt_token": field(first, "attempt_token"), "lang": "cs"},
    )
    assert response.status_code == 409
    assert Attempt.objects.filter(status=Attempt.Status.IN_PROGRESS).count() == 1

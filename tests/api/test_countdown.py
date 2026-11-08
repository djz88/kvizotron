"""The participant's side of time: the notice, the countdown, automatic submission (FR-11)."""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import pytest
from django.test import RequestFactory

from app.api import play
from app.domain import attempts, authoring, run_links, run_schedule
from app.domain import settings as quiz_settings
from app.domain.models import Attempt, AttemptAnswer
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz, published_quiz
from tests.support.client import FormClient
from tests.support.clock import freeze
from tests.support.photos import Player, add_photo, field, photo_config, upload

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
KEY = "k" * 20
GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00\x00\x00\x00\x00"
    b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch, tmp_path, settings):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    freeze(monkeypatch, NOW)


def text(response):
    return response.content.decode()


def a_run(quiz=None, deadline=None, limit=None):
    if quiz is None:
        quiz = published_quiz(locales=("en",))
    elif authoring.latest_published(quiz) is None:
        authoring.publish(quiz, admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID, deadline_at=deadline, limit_sec=limit)


def start(client, run):
    return text(client.post(f"/r/{run.id}/start", {"lang": "en"}))


def number_config():
    return {
        "prompt": {"en": "How many?"},
        "value": "10",
        "tolerance": "0",
        "tolerance_kind": "absolute",
    }


def quiz_with_number_and_choice():
    quiz = make_quiz(locales=("en",))
    authoring.save_question(quiz, None, "number", number_config())
    add_question(quiz)
    return quiz


def question_of(attempt, type_id):
    return next(q["id"] for q in attempts.questions_of(attempt) if q["type"] == type_id)


def send(client, html, **fields):
    attempt_id = html.split("/a/")[1].split("/")[0]
    form = {
        "attempt_token": field(html, "attempt_token"),
        "submission_key": KEY,
        "lang": "en",
        **fields,
    }
    return attempt_id, client.post(f"/a/{attempt_id}/submit", form)


def test_a_limit_shows_a_countdown(client):
    run = a_run(limit=600)
    html = start(client, run)
    attempt = Attempt.objects.get(run=run)
    assert 'id="countdown"' in html
    assert 'data-remaining="600"' in html
    assert f'data-time-url="/a/{attempt.id}/time"' in html
    assert 'role="timer"' in html
    assert 'role="status"' in html


def test_a_deadline_alone_shows_a_countdown(client):
    html = start(client, a_run(deadline=NOW + timedelta(minutes=5)))
    assert 'data-remaining="300"' in html


def test_no_time_shows_no_countdown(client):
    assert 'id="countdown"' not in start(client, a_run())


def test_the_script_is_on_the_page(client):
    assert "countdown.js" in start(client, a_run(limit=600)) or "countdown.js" in text(
        client.get("/")
    )


def test_switching_keeps_the_real_time(client, monkeypatch):
    quiz = published_quiz(locales=("en",))
    run = a_run(quiz, limit=600)
    html = start(client, run)
    add_question(quiz, prompt="New")
    authoring.publish(quiz, admin_id=ADMIN_ID, decision="notify_switch")
    freeze(monkeypatch, NOW + timedelta(minutes=4))
    attempt = Attempt.objects.get(run=run)
    response = client.post(
        f"/a/{attempt.id}/switch", {"attempt_token": field(html, "attempt_token"), "lang": "en"}
    )
    assert 'data-remaining="360"' in text(response)


def test_the_quiz_page_states_limit_and_deadline(client):
    run = a_run(deadline=NOW + timedelta(hours=2), limit=900)
    html = text(client.get(f"/q/{run.quiz.slug}?lang=en"))
    assert "15 min" in html
    assert "2030-01-01 13:00 CET" in html
    assert "only" not in html


def test_it_states_the_real_time_when_the_deadline_shortens_it(client):
    run = a_run(deadline=NOW + timedelta(minutes=2), limit=900)
    html = text(client.get(f"/q/{run.quiz.slug}?lang=en"))
    assert "you will have only 2 min" in html


def test_seconds_are_said_in_the_last_minute(client):
    run = a_run(deadline=NOW + timedelta(seconds=40), limit=900)
    html = text(client.get(f"/q/{run.quiz.slug}?lang=en"))
    assert "you will have only 40 s" in html


def test_a_quiz_without_time_says_nothing_about_it(client):
    run = a_run()
    html = text(client.get(f"/q/{run.quiz.slug}?lang=en"))
    assert "Deadline" not in html
    assert "min" not in html.split('class="card"')[-1].split("</div>")[0]


def test_starting_is_not_blocked_close_to_the_deadline(client):
    run = a_run(deadline=NOW + timedelta(seconds=10), limit=900)
    assert 'data-remaining="10"' in start(client, run)


def test_auto_submit_stores_a_partly_answered_attempt(client):
    run = a_run(limit=600)
    attempt_id, response = send(client, start(client, run), auto_submit="1")
    assert response.status_code == 200
    assert Attempt.objects.get(pk=attempt_id).status == Attempt.Status.SUBMITTED


def test_auto_submit_treats_an_unreadable_answer_as_unanswered(client):
    run = a_run(quiz_with_number_and_choice(), limit=600)
    html = start(client, run)
    number = question_of(Attempt.objects.get(run=run), "number")
    attempt_id, response = send(client, html, auto_submit="1", **{f"{number}:value": "abc"})
    assert response.status_code == 200
    stored = Attempt.objects.get(pk=attempt_id)
    assert stored.status == Attempt.Status.SUBMITTED
    assert stored.score == 0


def test_auto_submit_keeps_the_readable_answers(client):
    run = a_run(quiz_with_number_and_choice(), limit=600)
    html = start(client, run)
    attempt = Attempt.objects.get(run=run)
    number = question_of(attempt, "number")
    choice = question_of(attempt, "choice")
    attempt_id, _response = send(
        client,
        html,
        auto_submit="1",
        **{f"{number}:value": "10", f"{choice}:options[]": ["nonexistent"]},
    )
    assert Attempt.objects.get(pk=attempt_id).score == 1


def test_a_normal_submit_still_refuses_an_unreadable_answer(client):
    run = a_run(quiz_with_number_and_choice(), limit=600)
    html = start(client, run)
    number = question_of(Attempt.objects.get(run=run), "number")
    attempt_id, response = send(client, html, **{f"{number}:value": "abc"})
    assert response.status_code == 400
    assert Attempt.objects.get(pk=attempt_id).status == Attempt.Status.IN_PROGRESS


def photo_run():
    quiz = make_quiz()
    add_photo(quiz)
    add_photo(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID, limit_sec=600)


def test_auto_submit_drops_a_refused_photo_and_stores_the_rest():
    player = Player(photo_run())
    first, second = [q["id"] for q in player.questions]
    response = player.submit(
        {
            f"{first}:image": upload(GIF, name="fotka.gif"),
            f"{second}:image": upload(),
            "auto_submit": "1",
        }
    )
    assert response.status_code == 200
    stored = Attempt.objects.get(pk=player.attempt.pk)
    assert stored.status in Attempt.FINISHED
    assert [row.question_id for row in stored.answers.all()] == [second]


def test_a_normal_submit_still_refuses_that_photo():
    player = Player(photo_run())
    first, _second = [q["id"] for q in player.questions]
    response = player.submit({f"{first}:image": upload(GIF, name="fotka.gif")})
    assert response.status_code == 400
    assert Attempt.objects.get(pk=player.attempt.pk).status == Attempt.Status.IN_PROGRESS


def test_auto_submit_says_the_time_ran_out(client):
    _id, response = send(client, start(client, a_run(limit=600)), auto_submit="1")
    assert "The time ran out" in text(response)


def test_a_normal_submit_does_not_say_it(client):
    _id, response = send(client, start(client, a_run(limit=600)))
    assert "The time ran out" not in text(response)


def test_a_repeated_auto_submit_with_the_same_key_stores_once(client):
    html = start(client, a_run(limit=600))
    attempt_id, first = send(client, html, auto_submit="1")
    _id, second = send(client, html, auto_submit="1")
    assert (first.status_code, second.status_code) == (200, 200)
    assert Attempt.objects.get(pk=attempt_id).status == Attempt.Status.SUBMITTED


def test_a_late_auto_submit_gets_the_expired_message(client, monkeypatch):
    html = start(client, a_run(limit=600))
    freeze(monkeypatch, NOW + timedelta(seconds=601))
    _id, response = send(client, html, auto_submit="1")
    assert response.status_code == 410
    assert "run out" in text(response)


def test_test_link_is_timed_too():
    quiz = published_quiz(locales=("en",))
    quiz_settings.set_override(quiz_settings.ATTEMPT_LIMIT, quiz, "10", admin_id=None)
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    html = text(FormClient().post(f"/r/{link.run_id}/start", {"lang": "en"}))
    assert 'data-remaining="600"' in html


def test_the_theme_styles_the_countdown_and_hides_the_announcement(client):
    response = client.get("/m/theme.default/theme.css")
    css = b"".join(response.streaming_content).decode()
    assert ".countdown {" in css
    assert ".visually-hidden {" in css


class SlowBody:
    """A body that arrives after the limit, as a slow phone or a trickling client sends it."""

    def __init__(self, stream, arrive):
        self.stream = stream
        self.arrive = arrive

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def read(self, *args):
        self.arrive()
        return self.stream.read(*args)

    def readline(self, *args):
        self.arrive()
        return self.stream.readline(*args)


def test_a_body_finishing_after_the_limit_is_late(client, monkeypatch):
    html = start(client, a_run(limit=600))
    attempt_id = html.split("/a/")[1].split("/")[0]
    request = RequestFactory().post(
        f"/a/{attempt_id}/submit",
        urlencode(
            {"attempt_token": field(html, "attempt_token"), "submission_key": KEY, "lang": "en"}
        ),
        content_type="application/x-www-form-urlencoded",
    )
    request.locale = "en"
    request._stream = SlowBody(
        request._stream, lambda: freeze(monkeypatch, NOW + timedelta(seconds=601))
    )
    response = play.submit(request, UUID(attempt_id))
    assert response.status_code == 410
    assert Attempt.objects.get(pk=attempt_id).status == Attempt.Status.IN_PROGRESS


def test_a_body_finishing_within_the_limit_counts(client, monkeypatch):
    html = start(client, a_run(limit=600))
    attempt_id = html.split("/a/")[1].split("/")[0]
    request = RequestFactory().post(
        f"/a/{attempt_id}/submit",
        urlencode(
            {"attempt_token": field(html, "attempt_token"), "submission_key": KEY, "lang": "en"}
        ),
        content_type="application/x-www-form-urlencoded",
    )
    request.locale = "en"
    request._stream = SlowBody(
        request._stream, lambda: freeze(monkeypatch, NOW + timedelta(seconds=600))
    )
    assert play.submit(request, UUID(attempt_id)).status_code == 200


def test_a_late_photo_after_the_deadline_closed_the_run_gets_the_message(monkeypatch):
    quiz = make_quiz(locales=("en",))
    add_photo_en(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, deadline_at=NOW + timedelta(minutes=5))
    player = Player(run)
    question = player.question("image_answer")
    freeze(monkeypatch, NOW + timedelta(minutes=5, seconds=1))
    run_schedule.settle()
    response = player.submit({f"{question}:image": upload(), "auto_submit": "1", "lang": "en"})
    assert response.status_code == 410
    assert "run out" in text(response)
    assert not AttemptAnswer.objects.exists()


def test_a_photo_long_after_the_end_stays_unread(monkeypatch):
    quiz = make_quiz(locales=("en",))
    add_photo_en(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, deadline_at=NOW + timedelta(minutes=5))
    player = Player(run)
    question = player.question("image_answer")
    freeze(monkeypatch, NOW + timedelta(hours=1))
    run_schedule.settle()
    assert player.submit({f"{question}:image": upload()}).status_code == 415


def add_photo_en(quiz):
    authoring.save_question(
        quiz,
        None,
        "image_answer",
        photo_config(locale="en"),
        points=10,
        scoring="partial",
    )

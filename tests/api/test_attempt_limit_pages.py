"""Test add-ons: what a participant reads about the limit of attempts."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.contracts import AFTER_PASS, MAX_ATTEMPTS, PASS_MARK, REPEAT_ATTEMPTS, UNFINISHED_ATTEMPT
from app.domain import authoring
from app.domain.models import Attempt
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
HTMX = {"HX-Request": "true"}


def a_run(limit="2", mark="0", **rules):
    rules = {REPEAT_ATTEMPTS: "allow", MAX_ATTEMPTS: limit, UNFINISHED_ATTEMPT: "submitted"} | rules
    return authoring.open_run(
        published_quiz("kviz", ("cs", "en", "uk")),
        admin_id=ADMIN_ID,
        rules=rules,
        results={PASS_MARK: mark},
    )


def text(response):
    return response.content.decode()


def play(client, run, lang="en"):
    return client.post(f"/r/{run.id}/start", {"lang": lang}, headers=HTMX)


def finish_last(run, score="0"):
    Attempt.objects.filter(run=run, status=Attempt.Status.IN_PROGRESS).update(
        status=Attempt.Status.SUBMITTED,
        submitted_at=datetime(2030, 1, 1, tzinfo=UTC),
        score=Decimal(score),
        max_score=Decimal(1),
    )


def test_quiz_page_says_attempts_left():
    """AC-173: the quiz page says how many attempts are left."""
    run = a_run("2")
    client = FormClient()
    assert "Attempts left: 2" in text(client.get(f"/q/{run.quiz.slug}?lang=en"))
    play(client, run)
    finish_last(run)
    assert "Attempts left: 1" in text(client.get(f"/q/{run.quiz.slug}?lang=en"))
    assert "Zbývající pokusy: 1" in text(client.get(f"/q/{run.quiz.slug}?lang=cs"))
    assert "Залишилось спроб: 1" in text(client.get(f"/q/{run.quiz.slug}?lang=uk"))


def test_no_limit_says_nothing():
    run = a_run("0")
    assert "Attempts left" not in text(FormClient().get(f"/q/{run.quiz.slug}?lang=en"))


def test_used_all_message_with_kept_result():
    """AC-173: all attempts used: message with the kept result."""
    run = a_run("1", mark="50")
    client = FormClient()
    play(client, run)
    finish_last(run, "0")
    response = play(client, run)
    assert response.status_code == 409
    html = text(response)
    assert "You have used all 1 attempts." in html
    assert "Not passed" in html
    assert "/v/" in html
    assert "One attempt per browser" not in html
    assert "Využili jste všechny pokusy (1)." in text(play(client, run, "cs"))


def test_already_passed_message():
    """AC-173: already passed: message with the kept result."""
    run = a_run("3", mark="50", after_pass="stop")
    client = FormClient()
    play(client, run)
    finish_last(run, "1")
    html = text(play(client, run))
    assert "You have already passed." in html
    assert "Passed" in html
    assert "/v/" in html
    assert "Test už máte splněný." in text(play(client, run, "cs"))


def test_forbid_message_is_unchanged():
    run = a_run("0", repeat_attempts="forbid")
    client = FormClient()
    play(client, run)
    finish_last(run)
    html = text(play(client, run))
    assert "You have already played this run in this browser." in html
    assert "One attempt per browser applies." in html


def test_may_restart_follows_the_limit():
    run = a_run("2")
    client = FormClient()
    play(client, run)
    assert "data-may-restart" in text(client.get(f"/q/{run.quiz.slug}?lang=en"))
    play(client, run)  # restart abandons the first: nothing is left
    assert "data-may-restart" not in text(client.get(f"/q/{run.quiz.slug}?lang=en"))


def test_test_link_ignores_limit():
    from app.domain import run_links, settings

    quiz = published_quiz("test-link")
    settings.set_override(REPEAT_ATTEMPTS, quiz, "forbid", admin_id=None)
    settings.set_override(MAX_ATTEMPTS, quiz, "1", admin_id=None)
    settings.set_override(AFTER_PASS, quiz, "stop", admin_id=None)
    link = run_links.create(quiz, authoring.latest_published(quiz), expires_at=None, admin_id="a")
    client = FormClient()
    for _ in range(3):
        assert play(client, link.run).status_code == 200


def test_quiz_page_without_attempts_has_no_start_form():
    """AC-173: nothing is offered once every attempt is used."""
    run = a_run("2")
    client = FormClient()
    for _ in range(2):
        play(client, run)
        finish_last(run)
    html = text(client.get(f"/q/{run.quiz.slug}?lang=en"))
    assert "You have used all 2 attempts." in html
    assert "/v/" in html
    assert "data-start-form" not in html
    assert "Attempts left" not in html


def test_quiz_page_after_a_pass_that_stops_has_no_start_form():
    """AC-173: a pass that ends the test offers no new start."""
    run = a_run("3", mark="50", after_pass="stop")
    client = FormClient()
    play(client, run)
    finish_last(run, "1")
    html = text(client.get(f"/q/{run.quiz.slug}?lang=en"))
    assert "You have already passed." in html
    assert "data-start-form" not in html
    assert "Start again" not in html


def test_quiz_page_with_attempts_left_has_the_start_form():
    run = a_run("2")
    client = FormClient()
    play(client, run)
    finish_last(run)
    html = text(client.get(f"/q/{run.quiz.slug}?lang=en"))
    assert "data-start-form" in html
    assert "Attempts left: 1" in html
    assert "You have used all" not in html


def test_conflict_message_for_stopping_after_a_pass():
    """AC-173: the clash with "nothing is kept" says what is wrong, in both admin languages."""
    from django.utils import translation

    from app.api.admin_forms import conflict_messages

    with translation.override("en"):
        assert conflict_messages([AFTER_PASS]) == [
            "Nothing is kept, which does not go with stopping attempts after passing."
        ]
    with translation.override("cs"):
        assert "po splnění" in conflict_messages([AFTER_PASS])[0]


def test_every_message_with_a_count_is_marked_as_counted():
    from app.api.play import COUNTED_MESSAGES, MESSAGES

    assert {code for code, text in MESSAGES.items() if "%(count)s" in str(text)} == COUNTED_MESSAGES

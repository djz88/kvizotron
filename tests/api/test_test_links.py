"""Test links from both sides: what a tester gets, and what the admin sees (AC-46, AC-47)."""

import logging
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from app.domain import attempts, authoring, quiz_state, run_links
from app.domain.models import Attempt, QuizRun, RunTestLink
from tests.domain.helpers import ADMIN_ID, OPTION_A, add_question, make_quiz, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
REPO = Path(__file__).resolve().parents[2]


def text(response):
    return response.content.decode()


def a_link(quiz=None, **fields):
    quiz = quiz or published_quiz(locales=("cs", "en"))
    revision = authoring.latest_published(quiz)
    return run_links.create(quiz, revision, expires_at=fields.get("expires_at"), admin_id=ADMIN_ID)


def started(client, link):
    return client.post(f"/r/{link.run_id}/start", {"lang": "en"})


def field(html, name):
    return html.split(f'name="{name}" value="')[1].split('"')[0]


def test_link_page_plays_to_a_result_without_login():
    link = a_link()
    client = FormClient()
    assert client.get(f"/t/{link.token}?lang=en").status_code == 200
    html = text(started(client, link))
    attempt = Attempt.objects.get()
    question = attempts.questions_of(attempt)[0]
    result = client.post(
        f"/a/{attempt.id}/submit",
        {
            "attempt_token": field(html, "attempt_token"),
            "submission_key": field(html, "submission_key"),
            "lang": "en",
            f"{question['id']}:options[]": [OPTION_A],
        },
    )
    assert "Your score" in text(result)


def test_every_step_says_it_is_a_test():
    link = a_link()
    client = FormClient()
    mark = "does not count"
    assert mark in text(client.get(f"/t/{link.token}?lang=en"))
    html = text(started(client, link))
    assert mark in html
    attempt = Attempt.objects.get()
    result = client.post(
        f"/a/{attempt.id}/submit",
        {
            "attempt_token": field(html, "attempt_token"),
            "submission_key": field(html, "submission_key"),
            "lang": "en",
        },
    )
    assert mark in text(result)


def test_a_normal_run_has_no_test_mark():
    quiz = published_quiz(locales=("cs", "en"))
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    client = FormClient()
    assert "does not count" not in text(client.get(f"/q/{quiz.slug}?lang=en"))
    assert "does not count" not in text(client.post(f"/r/{run.id}/start", {"lang": "en"}))


def test_invalid_cancelled_and_expired_links_give_one_same_message():
    quiz = published_quiz()
    cancelled = a_link(quiz)
    run_links.cancel(cancelled, admin_id=ADMIN_ID)
    expired = a_link(quiz, expires_at=timezone.now() - timedelta(minutes=1))
    client = FormClient()
    bodies = [
        client.get(f"/t/{token}?lang=en") for token in (cancelled.token, expired.token, "x" * 43)
    ]
    assert {response.status_code for response in bodies} == {200}
    assert len({text(response) for response in bodies}) == 1


def test_link_pages_carry_noindex_and_no_referrer():
    link = a_link()
    for token in (link.token, "x" * 43):
        response = FormClient().get(f"/t/{token}")
        assert response["X-Robots-Tag"] == "noindex"
        assert response["Referrer-Policy"] == "no-referrer"


def test_token_never_reaches_the_log(caplog):
    link = a_link()
    ended = a_link(link.run.quiz)
    run_links.cancel(ended, admin_id=ADMIN_ID)
    with caplog.at_level(logging.DEBUG):
        client = FormClient()
        client.get(f"/t/{link.token}")
        client.get(f"/t/{ended.token}")
        client.get("/t/" + "y" * 43)
    assert link.token not in caplog.text
    assert ended.token not in caplog.text
    assert "y" * 43 not in caplog.text


def test_deployment_logs_no_request_paths():
    assert "access-logfile" not in (REPO / "Dockerfile").read_text()
    assert "log" not in (REPO / "deploy" / "Caddyfile").read_text().replace("logs", "")


@pytest.mark.parametrize("htmx", [True, False])
def test_submit_after_cancel_from_open_page_shows_clear_message(htmx):
    link = a_link()
    client = FormClient()
    html = text(started(client, link))
    attempt = Attempt.objects.get()
    run_links.cancel(link, admin_id=ADMIN_ID)
    headers = {"HTTP_HX_REQUEST": "true"} if htmx else {}
    response = client.post(
        f"/a/{attempt.id}/submit",
        {
            "attempt_token": field(html, "attempt_token"),
            "submission_key": field(html, "submission_key"),
            "lang": "en",
        },
        **headers,
    )
    assert response.status_code == 410
    assert "This test has ended." in text(response)


def test_admin_form_lists_draft_published_and_older_not_a_test_copy(logged_in):
    quiz = published_quiz()
    add_question(quiz, prompt="Další")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    add_question(quiz, prompt="Ještě další")
    run_links.create(quiz, None, expires_at=None, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/tests?lang=en"))
    form = html.split('name="version"')[1].split("</select>")[0]
    assert form.count("<option") == 3
    assert 'value="draft"' in form
    assert 'value="1"' in form
    assert 'value="2"' in form


def test_admin_creates_a_link_on_the_chosen_version(logged_in):
    quiz = published_quiz()
    add_question(quiz, prompt="Další")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/tests", {"version": "1", "expires_at": ""})
    assert response.status_code == 302
    link = RunTestLink.objects.get()
    assert link.run.current_revision.revision_no == 1
    assert link.expires_at is None
    assert link.created_by


def test_no_draft_offers_no_draft(logged_in):
    quiz = published_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/tests?lang=en"))
    assert 'value="draft"' not in html


def test_draft_with_problems_is_refused_listing_them(logged_in):
    quiz = make_quiz()
    add_question(quiz, correct="")
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/tests?lang=en", {"version": "draft"})
    assert response.status_code == 200
    assert 'role="alert"' in text(response)
    assert "Question 1" in text(response)
    assert not RunTestLink.objects.exists()


def test_past_end_date_is_refused_keeping_the_form(logged_in):
    quiz = published_quiz()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/tests?lang=en",
        {"version": "1", "expires_at": "2020-01-01T10:00"},
    )
    assert response.status_code == 200
    assert "2020-01-01T10:00" in text(response)
    assert not RunTestLink.objects.exists()


def test_end_date_is_stored_as_utc(logged_in):
    quiz = published_quiz()
    logged_in.post(
        f"/admin/quizzes/{quiz.id}/tests", {"version": "1", "expires_at": "2099-01-01T10:00"}
    )
    expires = RunTestLink.objects.get().expires_at
    assert expires.isoformat().startswith("2099-01-01T10:00:00+00:00")


def test_tab_lists_links_with_version_end_state_and_attempt_count(logged_in):
    quiz = published_quiz()
    link = a_link(quiz, expires_at=timezone.now() + timedelta(days=1))
    attempts.start(QuizRun.all_kinds.get(pk=link.run_id))
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/tests?lang=en"))
    assert f"/t/{link.token}" in html
    assert "Active" in html
    assert "1" in html
    run_links.cancel(link, admin_id=ADMIN_ID)
    assert "Cancelled" in text(logged_in.get(f"/admin/quizzes/{quiz.id}/tests?lang=en"))


def test_a_tab_is_in_the_quiz_header(logged_in):
    quiz = published_quiz()
    page = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert f"/admin/quizzes/{quiz.id}/tests" in page


def test_tab_lists_attempts_with_score_duration_and_start(logged_in):
    quiz = published_quiz()
    link = a_link(quiz)
    run = QuizRun.all_kinds.get(pk=link.run_id)
    begun = attempts.start(run)
    question = attempts.questions_of(begun.attempt)[0]
    answers = {question["id"]: {"options": [OPTION_A]}}
    attempts.submit(begun.attempt.id, begun.token, answers, begun.submission_key)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/tests?lang=en"))
    assert "Submitted" in html
    assert "1 / 1" in html
    assert timezone.now().strftime("%Y-%m-%d") in html


def test_tab_says_anyone_with_the_link_sees_the_questions(logged_in):
    quiz = published_quiz()
    assert "Anyone with the link" in text(logged_in.get(f"/admin/quizzes/{quiz.id}/tests?lang=en"))


def test_cancel_and_delete_ask_first_and_work(logged_in):
    quiz = published_quiz()
    link = a_link(quiz)
    base = f"/admin/tests/{link.id}"
    assert "Please confirm" in text(logged_in.get(f"{base}/delete?lang=en"))
    assert RunTestLink.objects.filter(pk=link.pk).exists()
    assert logged_in.post(f"{base}/cancel").status_code == 302
    assert logged_in.post(f"{base}/attempts/delete").status_code == 302
    assert run_links.find_playable(link.token) is None
    assert logged_in.post(f"{base}/delete").status_code == 302
    assert not RunTestLink.objects.exists()


def test_cancel_requires_post_and_every_action_requires_login(logged_in):
    quiz = published_quiz()
    link = a_link(quiz)
    base = f"/admin/tests/{link.id}"
    assert logged_in.get(f"{base}/cancel").status_code == 405
    assert "Please confirm" in text(logged_in.get(f"{base}/attempts/delete?lang=en"))
    anonymous = FormClient()
    for path in (f"{base}/cancel", f"{base}/delete", f"{base}/attempts/delete"):
        assert anonymous.post(path).status_code == 302
    assert anonymous.get(f"/admin/quizzes/{quiz.id}/tests").status_code == 302
    assert run_links.find_playable(link.token) == link


def test_quiz_with_an_active_link_looks_the_same_on_runs_page(logged_in):
    quiz = published_quiz()
    before = quiz_state.of(quiz)
    page = text(logged_in.get(f"/admin/quizzes/{quiz.id}/runs?lang=en"))
    link = a_link(quiz)
    attempts.start(QuizRun.all_kinds.get(pk=link.run_id))
    assert quiz_state.of(quiz) == before
    assert text(logged_in.get(f"/admin/quizzes/{quiz.id}/runs?lang=en")).count("<tr") == page.count(
        "<tr"
    )

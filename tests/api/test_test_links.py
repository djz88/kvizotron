"""Test links from both sides: what a tester gets, and what the admin sees (AC-46, AC-47)."""

import logging
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from app.domain import attempts, authoring, quiz_state, run_links, settings
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
    assert expires.isoformat().startswith("2099-01-01T09:00:00+00:00")


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


def test_a_link_end_is_read_and_shown_in_the_configured_zone(logged_in):
    quiz = published_quiz(locales=("cs", "en"))
    revision = authoring.latest_published(quiz)
    logged_in.post(
        f"/admin/quizzes/{quiz.id}/tests",
        {"version": str(revision.revision_no), "expires_at": "2099-01-01T12:00"},
    )
    link = RunTestLink.objects.get(run__quiz=quiz)
    assert link.expires_at.isoformat() == "2099-01-01T11:00:00+00:00"
    assert "2099-01-01 12:00 CET" in text(logged_in.get(f"/admin/quizzes/{quiz.id}/tests"))


def test_a_test_link_counts_down(client):
    quiz = published_quiz(locales=("cs", "en"))
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "10", admin_id=None)
    link = a_link(quiz)
    html = text(started(client, link))
    assert 'id="countdown"' in html
    assert "data-time-url" in html


# --- the shown address of one link (AC-167) ----------------------------------------------

HTMX = {"HTTP_HX_REQUEST": "true"}


def address_url(link):
    return f"/admin/tests/{link.id}/address"


def links_url(link):
    return f"/admin/quizzes/{link.run.quiz_id}/tests"


def test_the_address_of_a_link_has_a_pencil_and_saves(logged_in):
    """AC-167: the pencil changes only the shown address of that one link."""
    link = a_link()
    other = a_link(link.run.quiz)
    html = text(logged_in.get(links_url(link)))
    assert f'href="{links_url(link)}?edit=address-{link.id}"' in html
    response = logged_in.post(address_url(link), {"address": "10.0.0.5:8080"}, **HTMX)
    assert response.status_code == 200
    assert f"https://10.0.0.5:8080/t/{link.token}" in text(response)
    html = text(logged_in.get(links_url(link)))
    assert f'href="https://10.0.0.5:8080/t/{link.token}"' in html
    assert f">https://10.0.0.5:8080/t/{link.token}<" in html
    assert f'href="http://testserver/t/{other.token}"' in html


def test_the_pencil_says_edit_the_address(logged_in):
    link = a_link()
    html = text(logged_in.get(links_url(link) + "?lang=en"))
    block = html.split(f'id="name-address-{link.id}"')[1]
    pencil = block.split('class="inline-name-pencil"')[1].split(">")[0]
    assert 'title="Edit the address"' in pencil


def test_a_bad_address_keeps_the_field_with_its_message(logged_in):
    link = a_link()
    response = logged_in.post(address_url(link), {"address": "https://a.cz/x"}, **HTMX)
    assert response.status_code == 400
    html = text(response)
    assert 'value="https://a.cz/x"' in html
    assert "inline-name-error" in html
    response = logged_in.post(address_url(link), {"address": "https://a.cz/x"})
    assert response.status_code == 400
    html = text(response)
    assert 'name="address"' in html
    assert "<h1" in html or "quiz-header" in html
    link.refresh_from_db()
    assert link.shown_origin == ""


def test_an_empty_address_goes_back_to_the_admins_address(logged_in):
    link = a_link()
    run_links.set_origin(link, "a.cz", admin_id=ADMIN_ID)
    response = logged_in.post(address_url(link), {"address": ""}, **HTMX)
    assert response.status_code == 200
    assert f"http://testserver/t/{link.token}" in text(response)
    link.refresh_from_db()
    assert link.shown_origin == ""


def test_the_field_can_be_emptied_and_shows_the_admins_address_as_a_hint(logged_in):
    link = a_link()
    html = text(logged_in.get(address_url(link) + "?edit=1", **HTMX))
    field_tag = html.split('name="address"')[1].split(">")[0]
    assert "required" not in field_tag
    assert 'placeholder="http://testserver"' in field_tag
    assert 'value="http://testserver"' in field_tag  # the current address, ready to edit
    assert f"/t/{link.token}" in html
    run_links.set_origin(link, "10.0.0.5:8080", admin_id=ADMIN_ID)
    html = text(logged_in.get(address_url(link) + "?edit=1", **HTMX))
    assert 'value="https://10.0.0.5:8080"' in html.split('name="address"')[1].split(">")[0]


def test_saving_the_admins_own_address_keeps_following_it(logged_in):
    """The prefilled address saved unchanged stays "the address the admin uses"."""
    link = a_link()
    response = logged_in.post(address_url(link), {"address": "http://testserver"}, **HTMX)
    assert response.status_code == 200
    link.refresh_from_db()
    assert link.shown_origin == ""


def test_the_note_says_only_the_copy_changes(logged_in):
    link = a_link()
    html = text(logged_in.get(links_url(link)))
    assert "Mění pouze zobrazení pro kopírování" in html


def test_without_javascript_the_pencil_opens_the_field_on_the_page(logged_in):
    link = a_link()
    other = a_link(link.run.quiz)
    html = text(logged_in.get(f"{links_url(link)}?edit=address-{link.id}"))
    assert html.count('name="address"') == 1
    # a <form> inside <p> is moved out of it by the browser, away from `.inline-name`
    assert not re.search(r"<p>[^<]*<span class=\"inline-name\" id=\"name-address", html)
    assert f'id="name-address-{link.id}"' in html
    assert f'id="name-address-{other.id}"' in html
    response = logged_in.get(address_url(link) + "?edit=1")
    assert response.status_code == 302
    assert response["Location"] == f"{links_url(link)}?edit=address-{link.id}"
    response = logged_in.post(address_url(link), {"address": "a.cz"})
    assert response.status_code == 302


def test_an_archived_quiz_shows_no_pencil_and_refuses_the_save(logged_in):
    link = a_link()
    authoring.archive_quiz(link.run.quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(links_url(link)))
    assert f'id="name-address-{link.id}"' not in html
    assert f'href="http://testserver/t/{link.token}"' in html
    response = logged_in.get(address_url(link) + "?edit=1", **HTMX)
    assert 'name="address"' not in text(response)
    assert "inline-name-pencil" not in text(response)
    response = logged_in.post(address_url(link), {"address": "a.cz"})
    assert response.status_code == 409
    assert f'id="name-address-{link.id}"' not in text(response)
    response = logged_in.post(address_url(link), {"address": "a.cz"}, **HTMX)
    assert response.status_code == 409
    link.refresh_from_db()
    assert link.shown_origin == ""


def test_test_link_shows_answers_at_the_end_even_after_close_and_says_when():
    quiz = published_quiz(locales=("cs", "en"))
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_close", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_LEVEL, quiz, "answers", admin_id=ADMIN_ID)
    link = a_link(quiz)
    client = FormClient()
    html = text(started(client, link))
    attempt = Attempt.objects.get()
    question = attempts.questions_of(attempt)[0]
    result = text(
        client.post(
            f"/a/{attempt.id}/submit",
            {
                "attempt_token": field(html, "attempt_token"),
                "submission_key": field(html, "submission_key"),
                "lang": "en",
                f"{question['id']}:options[]": [OPTION_A],
            },
        )
    )
    assert "reveal-list" in result
    assert "In a real run, the correct answers are shown only after the run closes." in result
    assert "at this link after the run closes" not in result  # the answers are already there

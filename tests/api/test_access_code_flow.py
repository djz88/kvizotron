"""AC-72: the access code on the pages: entered once, limited, and shown only once to the admin."""

import logging

import pytest

from app.api import rate_limit
from app.domain import access_codes, attempts, authoring, run_links, tokens
from app.domain.models import QuizRun
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
CODE = "ABCD2345"


@pytest.fixture(autouse=True)
def fresh_limiter():
    rate_limit.reset()
    yield
    rate_limit.reset()


def text(response):
    return response.content.decode()


def a_run(code=CODE) -> QuizRun:
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    if code:
        access_codes.set_code(run, code, admin_id=ADMIN_ID)
        run.refresh_from_db()
    return run


def enter(client, run, code, **extra):
    return client.post(f"/r/{run.id}/code", {"lang": "cs", "code": code}, **extra)


def start(client, run):
    return client.post(f"/r/{run.id}/start", {"lang": "cs"})


def test_quiz_page_asks_for_the_code_and_start_is_refused():
    run = a_run()
    client = FormClient()
    page = client.get(f"/q/{run.quiz.slug}")
    assert f"/r/{run.id}/code" in text(page) and f"/r/{run.id}/start" not in text(page)
    assert start(client, run).status_code == 403


def test_right_code_unlocks_and_start_works():
    run = a_run()
    client = FormClient()
    response = enter(client, run, "abcd2345")
    assert response.status_code == 302
    morsel = response.cookies[f"kvz_c_{run.id.hex}"]
    assert morsel["httponly"] and morsel["samesite"] == "Lax" and morsel["path"] == "/"
    assert CODE not in response["Location"]
    page = client.get(response["Location"])
    assert f"/r/{run.id}/start" in text(page)
    assert start(client, run).status_code == 200


def test_wrong_code_shows_the_page_with_an_error():
    run = a_run()
    client = FormClient()
    response = enter(client, run, "WRONG234")
    assert response.status_code == 403
    assert f"/r/{run.id}/code" in text(response)
    assert f"kvz_c_{run.id.hex}" not in response.cookies
    assert start(client, run).status_code == 403


def test_changed_code_stops_a_holder_of_the_old_cookie():
    run = a_run()
    client = FormClient()
    enter(client, run, CODE)
    access_codes.set_code(run, "WXYZ6789", admin_id=ADMIN_ID)
    assert start(client, run).status_code == 403
    page = client.get(f"/q/{run.quiz.slug}")
    assert f"/r/{run.id}/code" in text(page)


def test_removed_code_opens_run():
    run = a_run()
    access_codes.set_code(run, None, admin_id=ADMIN_ID)
    assert start(FormClient(), run).status_code == 200


def test_eleventh_wrong_code_in_a_minute_is_429(monkeypatch):
    run = a_run()
    client = FormClient()
    for _ in range(10):
        assert enter(client, run, "WRONG234").status_code == 403
    blocked = enter(client, run, "WRONG234")
    assert blocked.status_code == 429
    assert enter(client, run, CODE).status_code == 429


def test_limit_resets_after_a_minute():
    now = 1000.0
    for _ in range(10):
        rate_limit.record("code", "1.2.3.4", now)
    assert not rate_limit.allow("code", "1.2.3.4", now + 30)
    assert rate_limit.allow("code", "1.2.3.4", now + 61)
    assert rate_limit.allow("code", "5.6.7.8", now)


def test_limit_follows_the_client_ip(monkeypatch):
    run = a_run()
    for _ in range(10):
        enter(FormClient(), run, "WRONG234", headers={"X-Forwarded-For": "9.9.9.9"})
    assert (
        enter(FormClient(), run, "WRONG234", headers={"X-Forwarded-For": "9.9.9.9"}).status_code
        == 429
    )
    assert (
        enter(FormClient(), run, "WRONG234", headers={"X-Forwarded-For": "8.8.8.8"}).status_code
        == 403
    )


def test_client_ip_prefers_forwarded_for(rf):
    request = rf.get("/", HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2", REMOTE_ADDR="3.3.3.3")
    assert rate_limit.client_ip(request) == "2.2.2.2"  # the one the trusted proxy added
    assert rate_limit.client_ip(rf.get("/", REMOTE_ADDR="3.3.3.3")) == "3.3.3.3"


def test_limiter_forgets_idle_addresses():
    for number in range(50):
        rate_limit.record("code", f"10.0.0.{number}", 0.0)
    rate_limit.allow("code", "10.1.1.1", 1000.0)
    rate_limit.sweep(1000.0)
    assert rate_limit.tracked() == 0


def test_qr_and_link_have_no_code(logged_in):
    run = a_run()
    assert CODE not in text(logged_in.get(f"/admin/quizzes/{run.quiz_id}/qr.svg"))
    page = text(FormClient().get(f"/q/{run.quiz.slug}"))
    assert CODE not in page and run.access_code_hash not in page


def test_walkthrough_and_result_link_need_no_code():
    run = a_run()
    started = attempts.start(run, unlocked=True)
    attempts.submit(started.attempt.id, started.token, {}, started.submission_key)
    link = tokens.issue_result(started.attempt.id)
    response = FormClient().get(f"/v/{link}")
    assert response.status_code == 200 and "/code" not in text(response)
    authoring.close_run(run, admin_id=ADMIN_ID)
    page = FormClient().get(f"/q/{run.quiz.slug}/r/{run.id}/answers")
    assert page.status_code == 200 and f"/r/{run.id}/code" not in text(page)


def test_test_link_needs_no_code():
    quiz = published_quiz()
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    QuizRun.all_kinds.filter(pk=link.run_id).update(access_code_hash="x")
    client = FormClient()
    page = client.get(f"/t/{link.token}")
    assert f"/r/{link.run_id}/start" in text(page) and "/code" not in text(page)
    assert start(client, link.run).status_code == 200


def test_one_click_open_has_no_code(logged_in):
    quiz = published_quiz()
    logged_in.post(f"/admin/quizzes/{quiz.id}/runs")
    run = quiz.runs.get()
    assert run.access_code_hash == ""
    assert start(FormClient(), run).status_code == 200


def test_code_is_not_logged(caplog):
    run = a_run()
    with caplog.at_level(logging.DEBUG):
        enter(FormClient(), run, "WRONG234")
        enter(FormClient(), run, CODE)
    assert "WRONG234" not in caplog.text and CODE not in caplog.text


def test_new_code_shown_once(logged_in):
    run = a_run(code=None)
    response = logged_in.post(
        f"/admin/runs/{run.id}/code?lang=en", {"action": "set", "access_code": "mojekod9"}
    )
    assert response.status_code == 200 and "MOJEKOD9" in text(response)
    assert "no-store" in response["Cache-Control"]
    again = logged_in.get(f"/admin/runs/{run.id}?lang=en")
    assert "MOJEKOD9" not in text(again) and "mojekod9" not in text(again)
    run.refresh_from_db()
    assert access_codes.matches(run, "MOJEKOD9") and "MOJEKOD9" not in run.access_code_hash
    assert "access_code" not in logged_in.session.keys() and "MOJEKOD9" not in str(
        dict(logged_in.session)
    )


def test_admin_can_generate_and_remove(logged_in):
    run = a_run(code=None)
    shown = text(logged_in.post(f"/admin/runs/{run.id}/code?lang=en", {"action": "generate"}))
    run.refresh_from_db()
    assert run.access_code_hash
    code = next(c for c in _words(shown) if len(c) == 8 and access_codes.matches(run, c))
    assert code
    response = logged_in.post(f"/admin/runs/{run.id}/code?lang=en", {"action": "remove"})
    assert response.status_code == 302
    run.refresh_from_db()
    assert run.access_code_hash == ""


def _words(html):
    import re

    return re.findall(r"[A-Z0-9]{8}", html)


def test_admin_code_refused_on_closed_run(logged_in):
    run = a_run(code=None)
    authoring.close_run(run, admin_id=ADMIN_ID)
    response = logged_in.post(
        f"/admin/runs/{run.id}/code?lang=en", {"action": "set", "access_code": "mojekod9"}
    )
    run.refresh_from_db()
    assert run.access_code_hash == "" and response.status_code == 200


def test_plan_form_sets_the_code_and_shows_it_once(logged_in):
    quiz = published_quiz()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/plan?lang=en", {"access_code": "planned1", "generate_code": ""}
    )
    assert response.status_code == 200 and "PLANNED1" in text(response)
    run = quiz.runs.get()
    assert access_codes.matches(run, "PLANNED1")
    assert "PLANNED1" not in text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))


def test_plan_form_can_generate_a_code(logged_in):
    quiz = published_quiz()
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/plan?lang=en", {"generate_code": "on"})
    run = quiz.runs.get()
    assert response.status_code == 200 and run.access_code_hash
    assert any(access_codes.matches(run, word) for word in _words(text(response)))


def test_plan_without_a_code_redirects(logged_in):
    quiz = published_quiz()
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/plan?lang=en", {})
    assert response.status_code == 302 and quiz.runs.get().access_code_hash == ""


FORBID = {"repeat_attempts": "forbid", "unfinished_attempt": "continue"}


def locked_run(**rules):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, rules=rules)
    access_codes.set_code(run, CODE, admin_id=ADMIN_ID)
    run.refresh_from_db()
    return run


def test_locked_start_checks_nothing_about_the_person(monkeypatch):
    from app.domain.models import Participant

    run = locked_run(ask_name="required", ask_when="start", repeat_attempts="forbid")
    unlocked = FormClient()
    enter(unlocked, run, CODE)
    unlocked.post(f"/r/{run.id}/start", {"lang": "cs", "participant_name": "Jana"})
    before = Participant.objects.count()

    def probe(*args, **kwargs):
        raise AssertionError("a name was checked before the code")

    monkeypatch.setattr("app.domain.participants.name_is_taken", probe)
    response = FormClient().post(f"/r/{run.id}/start", {"lang": "cs", "participant_name": "Jana"})
    assert response.status_code == 403
    assert Participant.objects.count() == before
    assert f"kvz_p_{run.id.hex}" not in response.cookies


def test_a_started_participant_resumes_after_the_code_changes():
    run = locked_run(**FORBID)
    client = FormClient()
    enter(client, run, CODE)
    first = start(client, run)
    attempt = text(first).split("/a/")[1].split("/")[0]
    access_codes.set_code(run, "WXYZ6789", admin_id=ADMIN_ID)
    page = client.get(f"/q/{run.quiz.slug}")
    assert f"/r/{run.id}/start" in text(page)
    again = start(client, run)
    assert again.status_code == 200 and text(again).split("/a/")[1].split("/")[0] == attempt


def test_a_participant_without_an_open_attempt_is_stopped_after_the_change():
    run = locked_run(**FORBID)
    client = FormClient()
    enter(client, run, CODE)
    started = start(client, run)
    attempt_id = text(started).split("/a/")[1].split("/")[0]
    from app.domain.models import Attempt

    Attempt.objects.filter(pk=attempt_id).update(status=Attempt.Status.ABANDONED)
    access_codes.set_code(run, "WXYZ6789", admin_id=ADMIN_ID)
    assert start(client, run).status_code == 403
    assert f"/r/{run.id}/code" in text(client.get(f"/q/{run.quiz.slug}"))


def test_code_post_on_a_run_without_a_code_redirects_and_counts_nothing():
    run = a_run(code=None)
    for _ in range(12):
        response = enter(FormClient(), run, "WRONG234")
        assert response.status_code == 302
    assert rate_limit.tracked() == 0


def test_code_post_on_a_test_run_redirects():
    quiz = published_quiz()
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    response = enter(FormClient(), link.run, "WRONG234")
    assert response.status_code == 302 and response["Location"] == f"/t/{link.token}"
    assert rate_limit.tracked() == 0

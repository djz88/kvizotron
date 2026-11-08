"""AC-09, AC-78: the pages of a run that keeps nothing."""

import pytest

from app.domain import authoring, run_links, settings
from app.domain.models import Attempt, QuizRun
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient
from tests.support.photos import add_photo, field, photo_quiz

pytestmark = pytest.mark.django_db
NONE = {"profile": "none"}
GONE = "Tento pokus už byl odeslán nebo skončil."


def text(response):
    return response.content.decode()


@pytest.fixture
def run():
    return authoring.open_run(published_quiz(), admin_id=ADMIN_ID, data=NONE)


def started(client, run):
    html = text(client.post(f"/r/{run.id}/start", {"lang": "cs"}))
    attempt = html.split("/a/")[1].split("/")[0]
    return attempt, {
        "attempt_token": field(html, "attempt_token"),
        "submission_key": field(html, "submission_key"),
        "lang": "cs",
    }


def test_stateless_submit_shows_score_and_keeps_nothing(run):
    client = FormClient()
    attempt, form = started(client, run)
    response = client.post(f"/a/{attempt}/submit", form)
    assert response.status_code == 200
    assert "0 / 1" in text(response)
    assert not Attempt.objects.filter(status=Attempt.Status.SUBMITTED).exists()
    run.refresh_from_db()
    assert run.stateless_submitted == 1


def test_stateless_result_has_no_link(run):
    client = FormClient()
    attempt, form = started(client, run)
    html = text(client.post(f"/a/{attempt}/submit", form))
    assert "/v/" not in html
    assert "Výsledek už nepůjde znovu zobrazit" in html


def test_repeated_stateless_submit_is_gone_410(run):
    client = FormClient()
    attempt, form = started(client, run)
    client.post(f"/a/{attempt}/submit", form)
    again = client.post(f"/a/{attempt}/submit", form)
    assert again.status_code == 410
    assert GONE in text(again)
    run.refresh_from_db()
    assert run.stateless_submitted == 1


def test_gone_attempt_time_poll_is_410(run):
    client = FormClient()
    attempt, form = started(client, run)
    client.post(f"/a/{attempt}/submit", form)
    response = client.post(f"/a/{attempt}/time", {"attempt_token": form["attempt_token"]})
    assert response.status_code == 410


def test_unknown_attempt_is_still_404(run):
    response = FormClient().post(
        "/a/00000000-0000-4000-8000-000000000000/submit",
        {"attempt_token": "x", "submission_key": "k" * 20, "lang": "cs"},
    )
    assert response.status_code == 404


def test_quiz_settings_form_refuses_none_with_ask_name(logged_in):
    quiz = published_quiz()
    settings.set_global("ask_name", "required", admin_id=None)
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings?lang=cs",
        {"slug": quiz.slug, "data_profile": "none"},
    )
    assert str(settings.CATALOGUE["ask_name"].label) in text(response)
    assert settings.quiz_override(settings.DATA_PROFILE, quiz) is None


def test_global_settings_form_refuses_none_with_forbid(logged_in):
    settings.set_global("repeat_attempts", "forbid", admin_id=None)
    response = logged_in.post("/admin/settings?lang=cs", {"data_profile": "none"})
    assert str(settings.CATALOGUE["repeat_attempts"].label) in text(response)
    assert settings.resolve(settings.DATA_PROFILE) != "none"


def test_plan_form_names_each_conflicting_setting(logged_in):
    quiz = published_quiz()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/plan?lang=cs",
        {
            "starts_at": "",
            "deadline_at": "",
            "limit_minutes": "",
            "data_profile": "none",
            "retention_period": "30d",
            "ask_name": "required",
            "repeat_attempts": "forbid",
        },
    )
    html = text(response)
    assert str(settings.CATALOGUE["ask_name"].label) in html
    assert str(settings.CATALOGUE["repeat_attempts"].label) in html
    assert not QuizRun.objects.exists()


def test_run_page_shows_count_not_table(logged_in, run):
    client = FormClient()
    attempt, form = started(client, run)
    client.post(f"/a/{attempt}/submit", form)
    html = text(logged_in.get(f"/admin/runs/{run.id}?lang=cs"))
    assert html.count("Odesláno pokusů") == 1
    assert "Odesláno pokusů: 1" in html and "Odesláno pokusů: 0" not in html
    assert "data-attempt-row" not in html and "<table" not in html


def test_run_list_shows_the_stateless_count(logged_in, run):
    client = FormClient()
    attempt, form = started(client, run)
    client.post(f"/a/{attempt}/submit", form)
    html = text(logged_in.get(f"/admin/quizzes/{run.quiz.id}/runs?lang=cs"))
    assert "Odesláno pokusů: 1" in html and "Odesláno pokusů: 0" not in html
    assert '<td data-label="Odesláno">1</td>' in html or ">1</td>" in html


def test_quiz_page_warns_score_shown_once(run):
    html = text(FormClient().get(f"/q/{run.quiz.slug}?lang=cs"))
    assert "Výsledek se po odeslání ukáže jen jednou a nikam se neukládá." in html


def test_quiz_page_has_no_warning_under_other_profiles():
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert "nikam se neukládá" not in text(FormClient().get(f"/q/{quiz.slug}?lang=cs"))


def test_publish_page_notice_when_none_run_keeps_revision(logged_in, run):
    add_photo(run.quiz)
    page = text(logged_in.get(f"/admin/quizzes/{run.quiz.id}/publish?lang=cs"))
    response = logged_in.post(
        f"/admin/quizzes/{run.quiz.id}/publish?lang=cs",
        {
            "snapshot_hash": page.split('name="snapshot_hash" value="')[1].split('"')[0],
            "decision": "notify_switch",
        },
    )
    assert "ponechá svou revizi" in text(response)
    run.refresh_from_db()
    assert run.current_revision.revision_no == 1


def test_test_link_with_photo_question_is_not_called_stateless():
    quiz = photo_quiz()
    settings.set_override(settings.DATA_PROFILE, quiz, "none", admin_id=ADMIN_ID)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    html = text(FormClient().get(f"/t/{link.token}?lang=cs"))
    assert "nikam se neukládá" not in html

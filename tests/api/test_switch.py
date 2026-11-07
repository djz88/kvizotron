import re

import pytest

from app.domain import authoring
from app.domain.models import Attempt
from tests.api.test_play import HTMX, Play, hidden, text
from tests.domain.helpers import ADMIN_ID, OPTION_A, OPTION_B, add_question, open_quiz_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def run():
    return open_quiz_run(locales=("cs", "uk"), questions=2)


def question_ids(run):
    return [q["id"] for q in run.current_revision.snapshot_json["questions"]]


def publish(run, decision=authoring.Decision.NOTIFY_SWITCH, change=0):
    add_question(run.quiz, OPTION_B, prompt="Změněná", question_id=question_ids(run)[change])
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=decision)
    run.refresh_from_db()


def attempt_url(play, tail):
    return play.action.replace("/submit", f"/{tail}")


def test_questions_page_polls_every_30_seconds(client, run):
    html = text(Play(client, run).start_response)
    assert 'hx-trigger="every 30s"' in html
    assert "/revision-status" in html
    assert 'id="play-submit"' in html


def test_polling_replaces_only_itself_not_the_inherited_form_target(client, run):
    html = text(Play(client, run).start_response)
    polling = re.search(r'<div id="revision-notice"[^>]*>', html).group(0)
    assert 'hx-target="this"' in polling
    assert 'hx-disabled-elt="this"' in polling  # the form's "find button" matches nothing here


def test_switch_button_disables_itself(client, run):
    play = Play(client, run)
    publish(run)
    html = text(client.get(attempt_url(play, "revision-status"), headers=HTMX))
    assert 'hx-disabled-elt="this"' in html


def test_status_is_204_when_nothing_changed(client, run):
    play = Play(client, run)
    assert client.get(attempt_url(play, "revision-status")).status_code == 204


def test_status_is_204_after_let_finish(client, run):
    play = Play(client, run)
    publish(run, authoring.Decision.LET_FINISH)
    assert client.get(attempt_url(play, "revision-status")).status_code == 204


def test_status_returns_notice_and_switch_button_after_notify_switch(client, run):
    play = Play(client, run)
    publish(run)
    response = client.get(attempt_url(play, "revision-status"), headers=HTMX)
    html = text(response)
    assert response.status_code == 200
    assert 'id="play-submit"' in html and 'hx-swap-oob="true"' in html
    assert attempt_url(play, "switch") in html


def test_status_stops_polling_when_round_closed(client, run):
    play = Play(client, run)
    authoring.close_run(run, admin_id=ADMIN_ID)
    response = client.get(attempt_url(play, "revision-status"))
    assert response.status_code == 286 and response.content == b""


def test_status_stops_polling_for_unknown_attempt(client):
    url = "/a/00000000-0000-7000-8000-000000000009/revision-status"
    response = client.get(url)
    assert response.status_code == 286 and response.content == b""


def test_status_stops_polling_after_submission(client, run):
    play = Play(client, run)
    play.submit()
    assert client.get(attempt_url(play, "revision-status")).status_code == 286


def test_status_refuses_post(client, run):
    play = Play(client, run)
    assert client.post(attempt_url(play, "revision-status")).status_code == 405


def test_notice_is_translated(client, run):
    play = Play(client, run, lang="uk")
    publish(run)
    html = text(client.get(attempt_url(play, "revision-status") + "?lang=uk", headers=HTMX))
    assert "Перейти" in html


def test_questions_page_passes_the_language_to_polling(client, run):
    assert "revision-status?lang=uk" in text(Play(client, run, lang="uk").start_response)


def test_switch_returns_questions_with_kept_answer_and_changed_mark(client, run):
    play = Play(client, run)
    first, second = question_ids(run)
    publish(run, change=0)
    answers = {f"{first}:options[]": OPTION_A, f"{second}:options[]": OPTION_B}
    response = client.post(attempt_url(play, "switch"), play.fields | answers, headers=HTMX)
    html = text(response)
    assert response.status_code == 200
    assert html.count("checked") == 1 and f'value="{OPTION_B}" checked' in html
    assert html.count("question-changed") == 1
    assert "Změněná" in html
    assert "<html" not in html


def test_switch_without_htmx_returns_whole_page(client, run):
    play = Play(client, run)
    publish(run)
    response = client.post(attempt_url(play, "switch"), play.fields)
    assert response.status_code == 200
    assert "<html" in text(response) and "attempt_token" in text(response)


def test_old_tab_submit_after_switch_is_409_with_retarget(client, run):
    play = Play(client, run)
    publish(run)
    client.post(attempt_url(play, "switch"), play.fields, headers=HTMX)
    response = play.submit()
    assert response.status_code == 409
    assert response["HX-Retarget"] == "#play-message"


def test_switch_with_invalid_token_is_403(client, run):
    play = Play(client, run)
    publish(run)
    fields = play.fields | {"attempt_token": "nope"}
    assert client.post(attempt_url(play, "switch"), fields, headers=HTMX).status_code == 403


def test_switch_of_unknown_attempt_is_404(client):
    url = "/a/00000000-0000-7000-8000-000000000009/switch"
    assert client.post(url, {"lang": "cs"}, headers=HTMX).status_code == 404


def test_switch_refuses_get(client, run):
    assert client.get(attempt_url(Play(client, run), "switch")).status_code == 405


def test_switch_falls_back_when_language_was_removed(client, run):
    play = Play(client, run, lang="uk")
    quiz = run.quiz
    quiz.supported_locales = ["cs"]
    quiz.save()
    authoring.get_draft(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)
    response = client.post(attempt_url(play, "switch"), play.fields, headers=HTMX)
    assert response.status_code == 200
    assert hidden(text(response), "lang") == "cs"


def test_malformed_answers_are_dropped_not_refused(client, run):
    play = Play(client, run)
    first, second = question_ids(run)
    publish(run, change=0)
    fields = play.fields | {f"{second}:options[]": "garbage", f"{second}:other": "<script>x"}
    response = client.post(attempt_url(play, "switch"), fields, headers=HTMX)
    assert response.status_code == 200
    assert "checked" not in text(response) and "<script>x" not in text(response)


def test_switch_page_has_no_answer_key(client, run):
    play = Play(client, run)
    publish(run)
    html = text(client.post(attempt_url(play, "switch"), play.fields, headers=HTMX))
    assert "correct" not in html


def test_flow_after_switch_submits_and_scores_on_new_revision(client, run):
    play = Play(client, run)
    first, second = question_ids(run)
    publish(run, change=0)
    html = text(client.post(attempt_url(play, "switch"), play.fields, headers=HTMX))
    action = re.search(r'action="(/a/[^"]+/submit)"', html).group(1)
    fields = {
        "attempt_token": hidden(html, "attempt_token"),
        "submission_key": hidden(html, "submission_key"),
        "lang": "cs",
        f"{first}:options[]": OPTION_B,
        f"{second}:options[]": OPTION_A,
    }
    assert client.post(action, fields, headers=HTMX).status_code == 200
    submitted = Attempt.objects.get(status=Attempt.Status.SUBMITTED)
    assert submitted.score == 2 and submitted.revision_id == run.current_revision_id


def test_revision_polling_stops_for_a_pending_attempt(client):
    from app.domain.models import Attempt
    from tests.domain.helpers import open_quiz_run

    run = open_quiz_run(slug="poll")
    attempt = Attempt.objects.create(
        run=run, revision=run.current_revision, status=Attempt.Status.PENDING_GRADING
    )
    assert client.get(f"/a/{attempt.id}/revision-status").status_code == 286

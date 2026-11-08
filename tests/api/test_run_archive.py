"""Archiving an ended run, and counting what was never sent (FR-12, ADR-0048)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import attempts, authoring, run_schedule, settings
from app.domain.models import Attempt, AttemptAnswer, QuizRun
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, OPTION_A, add_question, make_quiz, published_quiz
from tests.support.clock import freeze
from tests.support.photos import Player, photo_quiz, run_of, upload

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch, tmp_path, settings):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    freeze(monkeypatch, NOW)


def text(response):
    return response.content.decode()


def stored(run):
    return QuizRun.objects.get(pk=run.pk)


def a_run(quiz=None, **fields):
    return authoring.open_run(quiz or published_quiz(), admin_id=ADMIN_ID, **fields)


def ended(quiz=None):
    run = a_run(quiz)
    authoring.close_run(run, admin_id=ADMIN_ID)
    return stored(run)


def public_quiz():
    quiz = make_quiz()
    add_question(quiz)
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "public", admin_id=ADMIN_ID)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return quiz


def test_only_an_ended_run_can_be_archived():
    for run in (a_run(), a_planned()):
        with pytest.raises(run_schedule.ScheduleRefused) as caught:
            run_schedule.archive(run, admin_id=ADMIN_ID)
        assert caught.value.code == "not_ended"


def a_planned():
    return run_schedule.plan(
        published_quiz(slug="plan"),
        starts_at=NOW + timedelta(hours=1),
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
    )


def test_it_keeps_its_data_and_can_be_restored():
    run = ended()
    closed_at = run.closed_at
    run_schedule.archive(run, admin_id=ADMIN_ID)
    assert stored(run).status == QuizRun.Status.ARCHIVED
    run_schedule.restore(run, admin_id=ADMIN_ID)
    assert stored(run).status == QuizRun.Status.CLOSED
    assert stored(run).closed_at == closed_at


def test_only_an_archived_run_can_be_restored():
    with pytest.raises(run_schedule.ScheduleRefused):
        run_schedule.restore(ended(), admin_id=ADMIN_ID)


def test_archive_and_restore_are_audited():
    run = ended()
    run_schedule.archive(run, admin_id=ADMIN_ID)
    run_schedule.restore(run, admin_id=ADMIN_ID)
    actions = set(AuditEvent.objects.filter(entity_id=str(run.id)).values_list("action", flat=True))
    assert {"run.archived", "run.restored"} <= actions


def test_it_leaves_the_list_and_returns_with_the_switch(logged_in):
    run = ended()
    url = f"/admin/quizzes/{run.quiz_id}/runs?lang=en"
    assert f"/admin/runs/{run.id}" in text(logged_in.get(url))
    response = logged_in.post(f"/admin/runs/{run.id}/archive")
    assert response.status_code == 302
    html = text(logged_in.get(url))
    assert f"/admin/runs/{run.id}" not in html
    assert "archived=1" in html
    assert f"/admin/runs/{run.id}" in text(logged_in.get(url + "&archived=1"))


def test_no_switch_without_an_archived_run(logged_in):
    run = ended()
    assert "archived=1" not in text(logged_in.get(f"/admin/quizzes/{run.quiz_id}/runs"))


def test_the_buttons_follow_the_status(logged_in):
    run = ended()
    assert f"/admin/runs/{run.id}/archive" in text(logged_in.get(f"/admin/runs/{run.id}"))
    run_schedule.archive(run, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert f"/admin/runs/{run.id}/restore" in html
    assert f"/admin/runs/{run.id}/archive" not in html


def test_a_running_run_has_no_archive_button(logged_in):
    run = a_run()
    assert f"/admin/runs/{run.id}/archive" not in text(logged_in.get(f"/admin/runs/{run.id}"))


def test_archive_hides_the_public_walkthrough_and_restore_returns_it(client):
    quiz = public_quiz()
    run = a_run(quiz)
    player = Player(run)
    player.plain({f"{player.question('choice')}:options[]": [OPTION_A]})
    authoring.close_run(run, admin_id=ADMIN_ID)
    url = f"/q/{quiz.slug}/r/{run.id}/answers"
    assert "not available" not in text(client.get(url + "?lang=en"))
    run_schedule.archive(stored(run), admin_id=ADMIN_ID)
    assert "not available" in text(client.get(url + "?lang=en"))
    run_schedule.restore(stored(run), admin_id=ADMIN_ID)
    assert "not available" not in text(client.get(url + "?lang=en"))


def photo_run():
    quiz = photo_quiz(level="public")
    return quiz, run_of(quiz)


def test_a_public_photo_of_an_archived_run_is_gone(client):
    quiz, run = photo_run()
    player = Player(run)
    question = player.question("image_answer")
    player.submit({f"{question}:image": upload()})
    row = AttemptAnswer.objects.get()
    AttemptAnswer.objects.filter(pk=row.pk).update(approved=True)
    authoring.close_run(run, admin_id=ADMIN_ID)
    url = f"/q/{quiz.slug}/r/{run.id}/photo/{row.id}"
    assert client.get(url).status_code == 200
    run_schedule.archive(stored(run), admin_id=ADMIN_ID)
    assert client.get(url).status_code == 204  # no photo, the same answer as any unavailable one


def result_link(response):
    return text(response).split('data-result-link="')[1].split('"')[0]


def test_a_private_result_link_still_works(client):
    quiz = public_quiz()
    run = a_run(quiz)
    player = Player(run)
    response = player.plain({f"{player.question('choice')}:options[]": [OPTION_A]})
    link = result_link(response)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run_schedule.archive(stored(run), admin_id=ADMIN_ID)
    result = client.get(link)
    assert result.status_code == 200
    assert "/ 1" in text(result)


def test_a_participants_own_photo_on_that_link_still_works(client):
    quiz, run = photo_run()
    player = Player(run)
    response = player.submit({f"{player.question('image_answer')}:image": upload()})
    link = result_link(response)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run_schedule.archive(stored(run), admin_id=ADMIN_ID)
    page = text(client.get(link))
    photo = page.split('<img src="')[1].split('"')[0]
    assert client.get(photo).status_code == 200


def test_attempts_of_an_archived_run_can_still_be_graded(logged_in):
    quiz, run = photo_run()
    player = Player(run)
    player.submit({f"{player.question('image_answer')}:image": upload()})
    authoring.close_run(run, admin_id=ADMIN_ID)
    run_schedule.archive(stored(run), admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/grading?run={run.id}"))
    assert str(AttemptAnswer.objects.get().id) in html


def test_unsent_on_an_ended_run_counts_all_in_progress():
    run = a_run()
    attempts.start(run)
    attempts.start(run)
    done = attempts.start(run)
    attempts.submit(done.attempt.id, done.token, {}, "k" * 20)
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert run_schedule.unsent(stored(run)) == 2


def test_unsent_on_a_running_run_counts_those_past_their_limit(monkeypatch):
    run = a_run(limit_sec=600)
    attempts.start(run)
    freeze(monkeypatch, NOW + timedelta(minutes=5))
    attempts.start(run)
    limit_end = NOW + timedelta(seconds=600)
    assert run_schedule.unsent(run, limit_end) == 0
    assert run_schedule.unsent(run, limit_end + timedelta(seconds=1)) == 1


def test_unsent_on_a_running_run_without_a_limit_is_zero():
    run = a_run()
    attempts.start(run)
    assert run_schedule.unsent(run, NOW + timedelta(days=1)) == 0


def test_unsent_ignores_replaced_attempts():
    quiz = published_quiz()
    run = a_run(quiz)
    started = attempts.start(run)
    add_question(quiz, prompt="Nová")
    authoring.publish(quiz, admin_id=ADMIN_ID, decision="notify_switch")
    attempts.switch(started.attempt.id, started.token, {})
    authoring.close_run(stored(run), admin_id=ADMIN_ID)
    assert Attempt.objects.filter(run=run).count() == 2
    assert run_schedule.unsent(stored(run)) == 1


def test_list_shows_status_times_and_unsent(logged_in):
    planned = a_planned()
    html = text(logged_in.get(f"/admin/quizzes/{planned.quiz_id}/runs?lang=en"))
    assert "Planned" in html
    assert "2030-01-01 12:00 CET" in html
    run = ended()
    started_run = a_run(run.quiz, deadline_at=NOW + timedelta(hours=2), limit_sec=600)
    attempts.start(started_run)
    html = text(logged_in.get(f"/admin/quizzes/{run.quiz_id}/runs?lang=en"))
    assert "Running" in html
    assert "Ended" in html
    assert "2030-01-01 13:00 CET" in html
    assert "10 min" in html
    assert "Not sent" in html


def test_run_page_shows_planned_status_and_unsent(logged_in):
    planned = a_planned()
    html = text(logged_in.get(f"/admin/runs/{planned.id}?lang=en"))
    assert "Planned" in html
    assert "Revision 1" in html
    assert f"/admin/runs/{planned.id}/plan" in html
    run = a_run()
    attempts.start(run)
    authoring.close_run(run, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert "Not sent: 1" in html


def test_archive_is_post_only(logged_in):
    run = ended()
    assert logged_in.get(f"/admin/runs/{run.id}/archive").status_code == 405
    assert stored(run).status == QuizRun.Status.CLOSED

"""The grading tab (AC-56). Tests use real photos through the real pages."""

from pathlib import Path

import pytest
from django.test import Client

from app.domain import authoring, grading, run_links, settings
from app.domain.models import Attempt, AttemptAnswer
from app.kernel.models import AuditEvent
from app.providers.media_local.models import MediaAsset
from tests.domain.helpers import ADMIN_ID, OPTION_A, published_quiz
from tests.support.client import FormClient
from tests.support.photos import Player, add_photo, photo_quiz, run_of, upload

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


def text(response):
    return response.content.decode()


def played(run):
    player = Player(run)
    player.submit({f"{player.question('image_answer')}:image": upload()})
    return player


def page(client, quiz, query=""):
    return text(client.get(f"/admin/quizzes/{quiz.id}/grading{query}"))


def graded_run(**fields):
    quiz = photo_quiz(**fields)
    return quiz, run_of(quiz)


def test_tab_shows_the_number_waiting_without_test_attempts(logged_in):
    quiz, run = graded_run()
    played(run)
    played(run)
    link = run_links.create(quiz, authoring.latest_published(quiz), expires_at=None, admin_id="a")
    played(link.run)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert f'href="/admin/quizzes/{quiz.id}/grading"' in html
    assert '<span class="chip chip-count">2</span>' in html


def test_tab_is_quiet_with_nothing_waiting(logged_in):
    quiz = published_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert "chip-count" not in html
    assert "<table" not in page(logged_in, quiz)


def test_by_question_gallery_shows_photos_and_fields(logged_in):
    quiz, run = graded_run()
    played(run)
    played(run)
    html = page(logged_in, quiz)
    rows = AttemptAnswer.objects.all()
    assert html.count('name="points"') == 2
    for row in rows:
        assert f"/admin/answers/{row.id}/photo" in html
    assert 'loading="lazy"' in html and "Vyfoťte" in html


def test_question_can_be_chosen_in_the_gallery(logged_in):
    quiz = photo_quiz()
    add_photo(quiz)
    run = run_of(quiz)
    player = Player(run)
    first, second = [question["id"] for question in player.questions]
    player.submit({f"{first}:image": upload()})
    html = page(logged_in, quiz, f"?question={second}")
    assert 'name="points"' not in html
    assert f"question={first}" in html
    assert 'name="points"' in page(logged_in, quiz, f"?question={first}")


def test_by_attempt_shows_all_stored_answers_and_grades_only_photos(logged_in):
    quiz = photo_quiz(plain=True)
    settings.set_override(settings.GRADING_VIEW, quiz, "by_attempt", admin_id=ADMIN_ID)
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    run = run_of(quiz)
    player = Player(run)
    player.submit(
        {
            f"{player.question('image_answer')}:image": upload(),
            f"{player.question('choice')}:options[]": [OPTION_A],
        }
    )
    html = page(logged_in, quiz)
    assert AttemptAnswer.objects.count() == 2
    assert html.count('name="points"') == 1
    assert "Otázka" in html and "Ano" in html


def test_setting_chooses_the_view(logged_in):
    quiz, run = graded_run()
    played(run)
    assert "grading-gallery" in page(logged_in, quiz)
    settings.set_override(settings.GRADING_VIEW, quiz, "by_attempt", admin_id=ADMIN_ID)
    assert "grading-attempts" in page(logged_in, quiz)


def test_running_run_comes_first(logged_in):
    quiz, old = graded_run()
    authoring.close_run(old, admin_id=ADMIN_ID)
    new = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = page(logged_in, quiz)
    assert html.index(f'value="{new.id}"') < html.index(f'value="{old.id}"')


def test_ended_run_can_be_chosen(logged_in):
    quiz, old = graded_run()
    played(old)
    authoring.close_run(old, admin_id=ADMIN_ID)
    new = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert 'name="points"' not in page(logged_in, quiz, f"?run={new.id}")
    assert 'name="points"' in page(logged_in, quiz, f"?run={old.id}")


def test_points_save_with_htmx(logged_in):
    quiz, run = graded_run()
    player = played(run)
    row = AttemptAnswer.objects.get()
    response = logged_in.post(
        f"/admin/answers/{row.id}/points", {"points": "5,5"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert "<html" not in text(response) and 'value="5.5"' in text(response)
    player.attempt.refresh_from_db()
    assert player.attempt.score == 7.5
    assert player.attempt.status == Attempt.Status.SUBMITTED


def test_points_save_without_htmx_goes_back_where_it_was(logged_in):
    quiz, run = graded_run()
    played(run)
    row = AttemptAnswer.objects.get()
    response = logged_in.post(
        f"/admin/answers/{row.id}/points",
        {"points": "1", "question": row.question_id, "page": "1"},
    )
    assert response.status_code == 302
    where = response["Location"]
    assert f"/admin/quizzes/{quiz.id}/grading" in where
    assert f"run={run.id}" in where and f"question={row.question_id}" in where


@pytest.mark.parametrize("value", ["9", "-1", "abc", "NaN", "", "1.23456"])
def test_invalid_points_show_a_message_and_keep_the_value(logged_in, value):
    quiz, run = graded_run()
    played(run)
    row = AttemptAnswer.objects.get()
    response = logged_in.post(
        f"/admin/answers/{row.id}/points", {"points": value}, headers={"HX-Request": "true"}
    )
    html = text(response)
    assert response.status_code == 200 and 'role="alert"' in html
    assert f'value="{value}"' in html
    row.refresh_from_db()
    assert row.manual_points is None


def test_invalid_points_without_script_show_the_page(logged_in):
    quiz, run = graded_run()
    played(run)
    row = AttemptAnswer.objects.get()
    response = logged_in.post(f"/admin/answers/{row.id}/points", {"points": "9"})
    html = text(response)
    assert response.status_code == 400 and "<html" in html
    assert 'role="alert"' in html and 'value="9"' in html


def test_delete_asks_first_and_removes_the_file(logged_in, media):
    quiz, run = graded_run()
    player = played(run)
    row = AttemptAnswer.objects.get()
    url = f"/admin/answers/{row.id}/delete"
    assert 'method="post"' in text(logged_in.get(url))
    assert MediaAsset.objects.count() == 1 and list(Path(media).iterdir())
    response = logged_in.post(url)
    assert response.status_code == 302 and f"run={run.id}" in response["Location"]
    assert MediaAsset.objects.count() == 0 and not list(Path(media).iterdir())
    row.refresh_from_db()
    player.attempt.refresh_from_db()
    assert row.removed and player.attempt.score == 2
    assert player.attempt.status == Attempt.Status.SUBMITTED
    html = page(logged_in, quiz)
    assert f"/admin/answers/{row.id}/photo" not in html
    assert logged_in.get(f"/admin/answers/{row.id}/photo").status_code == 404
    assert grading.waiting(run) == 0


def test_approve_only_offered_at_public_level(logged_in):
    quiz, run = graded_run()
    played(run)
    row = AttemptAnswer.objects.get()
    url = f"/admin/answers/{row.id}/approve"
    assert url not in page(logged_in, quiz)
    assert logged_in.post(url, {"approved": "1"}).status_code == 400
    row.refresh_from_db()
    assert not row.approved


def test_approve_is_not_offered_when_the_level_rose_after_the_attempt(logged_in):
    quiz, run = graded_run()
    played(run)
    row = AttemptAnswer.objects.get()
    settings.set_override("photo_visibility", quiz, "public", admin_id=ADMIN_ID)
    url = f"/admin/answers/{row.id}/approve"
    assert url not in page(logged_in, quiz)
    assert logged_in.post(url, {"approved": "1"}).status_code == 400


def test_approve_and_withdraw_at_public_level(logged_in):
    quiz, run = graded_run(level="public")
    played(run)
    row = AttemptAnswer.objects.get()
    url = f"/admin/answers/{row.id}/approve"
    assert url in page(logged_in, quiz)
    assert logged_in.post(url, {"approved": "1"}).status_code == 302
    row.refresh_from_db()
    assert row.approved
    logged_in.post(url, {"approved": ""})
    row.refresh_from_db()
    assert not row.approved
    assert AuditEvent.objects.filter(action="answer.approved").count() == 2


def test_test_link_has_a_grade_action_for_its_run(logged_in):
    quiz, _run = graded_run()
    link = run_links.create(quiz, authoring.latest_published(quiz), expires_at=None, admin_id="a")
    played(link.run)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/tests"))
    target = f"/admin/quizzes/{quiz.id}/grading?run={link.run_id}"
    assert target in html
    assert 'name="points"' in page(logged_in, quiz, f"?run={link.run_id}")


def test_run_of_another_quiz_is_404(logged_in):
    _quiz, run = graded_run()
    other = published_quiz(slug="jiny")
    response = logged_in.get(f"/admin/quizzes/{other.id}/grading?run={run.id}")
    assert response.status_code == 404
    assert logged_in.get(f"/admin/quizzes/{other.id}/grading?run=nonsense").status_code == 404


def test_login_required_everywhere_and_photo_no_store(logged_in):
    quiz, run = graded_run()
    played(run)
    row = AttemptAnswer.objects.get()
    for url in (
        f"/admin/quizzes/{quiz.id}/grading",
        f"/admin/answers/{row.id}/photo",
        f"/admin/answers/{row.id}/delete",
    ):
        response = Client().get(url)
        assert response.status_code == 302 and "/admin/login" in response["Location"]
    for action in ("points", "delete", "approve"):
        response = FormClient().post(f"/admin/answers/{row.id}/{action}", {"points": "1"})
        assert response.status_code == 302 and "/admin/login" in response["Location"]
    row.refresh_from_db()
    assert row.manual_points is None and not row.removed
    photo = logged_in.get(f"/admin/answers/{row.id}/photo")
    assert photo.status_code == 200 and photo["Content-Type"] == "image/webp"
    assert "no-store" in photo["Cache-Control"] and "private" in photo["Cache-Control"]


def test_fields_have_labels(logged_in):
    quiz, run = graded_run()
    played(run)
    html = page(logged_in, quiz)
    assert "<label" in html and 'for="' not in html.split('name="points"')[0][-10:]
    assert 'alt="' in html.split("/photo")[1].split(">")[0] or 'alt="' in html

import pytest

from app.domain import authoring
from app.domain.models import Quiz
from tests.domain.helpers import ADMIN_ID, add_question, open_quiz_run, published_quiz

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def base(quiz):
    return f"/admin/quizzes/{quiz.id}"


def archived(slug="kviz"):
    quiz = published_quiz(slug)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    return quiz


def test_archived_quiz_has_no_public_page(client):
    assert client.get(f"/q/{archived().slug}").status_code == 404


def test_archived_quiz_url_with_run_has_no_public_page(client):
    run = open_quiz_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert client.get(f"/q/{run.quiz.slug}/r/{run.id}").status_code == 200
    authoring.archive_quiz(run.quiz, admin_id=ADMIN_ID)
    assert client.get(f"/q/{run.quiz.slug}/r/{run.id}").status_code == 404


def test_archived_quiz_is_hidden_from_default_list_and_shown_by_filter(logged_in):
    quiz = archived()
    visible = published_quiz("viditelny")
    default = text(logged_in.get("/admin/quizzes"))
    assert f"/q/{quiz.slug}<" not in default and f"/q/{visible.slug}<" in default
    filtered = text(logged_in.get("/admin/quizzes?archived=1"))
    assert f"/q/{quiz.slug}<" in filtered and f"/q/{visible.slug}<" not in filtered


def test_archive_via_page_and_restore(logged_in):
    quiz = published_quiz()
    assert logged_in.post(f"{base(quiz)}/archive").status_code == 302
    assert Quiz.objects.get(pk=quiz.pk).archived_at is not None
    assert logged_in.post(f"{base(quiz)}/restore").status_code == 302
    assert Quiz.objects.get(pk=quiz.pk).archived_at is None


def test_archive_requires_post_and_login(client, logged_in):
    quiz = published_quiz()
    assert logged_in.get(f"{base(quiz)}/archive").status_code == 405
    logged_in.logout()
    client.post(f"{base(quiz)}/archive")
    assert Quiz.objects.get(pk=quiz.pk).archived_at is None


def test_archive_refusal_is_explained_on_edit_page(logged_in):
    run = open_quiz_run()
    response = logged_in.post(f"{base(run.quiz)}/archive")
    assert response.status_code == 409 and 'role="alert"' in text(response)
    assert Quiz.objects.get(pk=run.quiz.pk).archived_at is None


def test_edit_page_of_archived_quiz_is_read_only_with_restore(logged_in):
    quiz = archived()
    html = text(logged_in.get(f"{base(quiz)}/edit"))
    assert f"{base(quiz)}/restore" in html
    assert f"{base(quiz)}/duplicate" in html
    assert f"{base(quiz)}/publish" not in html
    assert "/questions/" not in html


def test_post_to_question_edit_of_archived_quiz_is_409(logged_in):
    quiz = published_quiz()
    question = authoring.editable_questions(quiz)[0]["id"]
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    response = logged_in.post(f"{base(quiz)}/questions/{question}/edit", {"prompt_cs": "X"})
    assert response.status_code == 409
    assert not quiz.revisions.filter(status="DRAFT").exists()


@pytest.mark.parametrize(
    "path",
    ["edit", "publish", "runs", "settings", "questions/new?type=choice", "draft/discard"],
)
def test_archived_quiz_refuses_every_editing_post(logged_in, path):
    quiz = archived()
    response = logged_in.post(f"{base(quiz)}/{path}", {"slug": "jine"})
    assert response.status_code == 409
    assert Quiz.objects.get(pk=quiz.pk).slug == quiz.slug


def test_restore_revision_of_archived_quiz_is_409(logged_in):
    quiz = archived()
    assert logged_in.post(f"{base(quiz)}/revisions/1/restore").status_code == 409


def test_revision_list_of_archived_quiz_offers_no_return(logged_in):
    assert "/revisions/1/restore" not in text(logged_in.get(f"{base(archived())}/revisions"))


def test_duplicate_form_prefills_free_slug(logged_in):
    quiz = published_quiz()
    assert 'value="kviz-copy"' in text(logged_in.get(f"{base(quiz)}/duplicate"))
    authoring.duplicate_quiz(quiz, "kviz-copy", admin_id=ADMIN_ID)
    assert 'value="kviz-copy-2"' in text(logged_in.get(f"{base(quiz)}/duplicate"))


def test_duplicate_redirects_to_new_quiz_editor(logged_in):
    quiz = published_quiz()
    response = logged_in.post(f"{base(quiz)}/duplicate", {"slug": "nova"})
    copy = Quiz.objects.get(slug="nova")
    assert response["Location"] == f"{base(copy)}/edit"


def test_duplicate_with_taken_slug_shows_error(logged_in):
    quiz = published_quiz()
    response = logged_in.post(f"{base(quiz)}/duplicate", {"slug": quiz.slug})
    assert response.status_code == 200 and Quiz.objects.count() == 1


def test_duplicate_of_long_slug_stays_within_limit(logged_in):
    quiz = published_quiz("x" * 80)
    html = text(logged_in.get(f"{base(quiz)}/duplicate"))
    assert 'value="' + "x" * 75 + '-copy"' in html


def test_duplicate_works_for_archived_quiz(logged_in):
    assert logged_in.post(f"{base(archived())}/duplicate", {"slug": "nova"}).status_code == 302


def test_restored_quiz_can_publish_and_open_round(logged_in):
    quiz = archived()
    logged_in.post(f"{base(quiz)}/restore")
    assert logged_in.post(f"{base(quiz)}/runs").status_code == 302
    add_question(quiz, prompt="Další")
    assert authoring.publish(quiz, admin_id=ADMIN_ID, decision="let_finish").revision_no == 2

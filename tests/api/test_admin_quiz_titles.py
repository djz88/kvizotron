"""Two quizzes that are not archived never share a title (the admin side)."""

from app.domain import authoring
from app.domain.models import Quiz
from tests.domain.helpers import ADMIN_ID

NEW = {"slug": "druhy", "supported_locales": ["cs"], "default_locale": "cs", "title_cs": "Evropa"}
TAKEN = "Jiný kvíz, který není v archivu, už tento název má. Zvolte jiný."


def evropa(slug="evropa"):
    return Quiz.objects.create(
        slug=slug, title={"cs": "Evropa"}, default_locale="cs", supported_locales=["cs"]
    )


def text(response):
    return response.content.decode()


def test_a_new_quiz_with_a_taken_title_is_refused_at_the_title(logged_in):
    evropa()
    response = logged_in.post("/admin/quizzes/new", NEW | {"title_cs": " EVROPA "})
    assert response.status_code == 200
    assert TAKEN in text(response)
    assert not Quiz.objects.filter(slug="druhy").exists()


def test_renaming_on_the_spot_to_a_taken_title_is_refused(logged_in):
    evropa()
    other = Quiz.objects.create(
        slug="jiny", title={"cs": "Jiný"}, default_locale="cs", supported_locales=["cs"]
    )
    response = logged_in.post(f"/admin/quizzes/{other.id}/name", {"name": "Evropa"})
    assert response.status_code == 400  # like any other name that does not validate
    assert TAKEN in text(response)
    other.refresh_from_db()
    assert other.title == {"cs": "Jiný"}


def test_restoring_an_archived_quiz_whose_title_was_taken_is_refused(logged_in):
    old = evropa()
    authoring.archive_quiz(old, admin_id=ADMIN_ID)
    evropa("nova")
    response = logged_in.post(f"/admin/quizzes/{old.id}/restore")
    assert response.status_code == 409
    assert "Nejdřív jeden z nich přejmenujte" in text(response)
    old.refresh_from_db()
    assert old.archived_at is not None


def test_a_duplicate_is_named_as_a_copy(logged_in):
    quiz = evropa()
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/duplicate", {"slug": "evropa-kopie"})
    assert response.status_code == 302
    assert Quiz.objects.get(slug="evropa-kopie").title == {"cs": "Evropa (kopie)"}


def test_a_quiz_that_already_shared_its_title_can_still_save_its_settings(logged_in):
    """Quizzes from before the rule keep working; only a changed title is checked."""
    first = evropa()
    evropa("jina")
    response = logged_in.post(
        f"/admin/quizzes/{first.id}/edit",
        {
            "supported_locales": ["cs"],
            "default_locale": "cs",
            "title_cs": "Evropa",
            "description_cs": "Nový",
        },
    )
    assert response.status_code == 302
    first.refresh_from_db()
    assert first.description == {"cs": "Nový"}
    assert logged_in.post(f"/admin/quizzes/{first.id}/name", {"name": "Evropa"}).status_code == 302


def published_evropa():
    """Published as "Název cs", renamed in the draft; then another quiz takes the old title."""
    from tests.domain.helpers import published_quiz

    quiz = published_quiz("evropa")
    quiz.title = {"cs": "Jiná"}
    quiz.save()
    authoring.get_draft(quiz)
    Quiz.objects.create(
        slug="nova", title={"cs": "Název cs"}, default_locale="cs", supported_locales=["cs"]
    )
    return quiz


def test_going_back_to_a_revision_whose_title_was_taken_is_refused_and_keeps_the_draft(logged_in):
    quiz = published_evropa()
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/revisions/1/restore", {"confirm": "1"})
    assert response.status_code == 409
    assert "Nejdřív jeden z nich přejmenujte" in text(response)
    quiz.refresh_from_db()
    assert quiz.title == {"cs": "Jiná"} and authoring.has_draft(quiz)


def test_discarding_a_draft_back_to_a_taken_title_is_refused_and_keeps_the_draft(logged_in):
    quiz = published_evropa()
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/draft/discard")
    assert response.status_code == 409
    assert "Nejdřív jeden z nich přejmenujte" in text(response)
    quiz.refresh_from_db()
    assert quiz.title == {"cs": "Jiná"} and authoring.has_draft(quiz)

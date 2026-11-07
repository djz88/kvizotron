import pytest

from app.domain import authoring, settings
from tests.domain.helpers import (
    ADMIN_ID,
    add_question,
    definition,
    make_quiz,
    open_quiz_run,
    published_quiz,
)

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def test_landing_lists_quizzes_with_open_run_only(client):
    open_quiz_run("bezi")
    published_quiz("nebezi")
    closed = open_quiz_run("zavreny")
    authoring.close_run(closed, admin_id=ADMIN_ID)
    html = text(client.get("/"))
    assert "/q/bezi" in html
    assert "/q/nebezi" not in html and "/q/zavreny" not in html


def test_landing_shows_featured_first(client):
    open_quiz_run("obycejny")
    open_quiz_run("hlavni", featured=True)
    html = text(client.get("/"))
    assert html.index("/q/hlavni") < html.index("/q/obycejny")
    assert "is-featured" in html


def test_landing_without_quizzes_says_so(client):
    assert "Teď neběží žádný kvíz." in text(client.get("/"))


def test_landing_is_in_chosen_language(client):
    assert "No quiz is running right now." in text(client.get("/?lang=en"))
    assert "Зараз не проходить жодна вікторина." in text(client.get("/?lang=uk"))


def test_quiz_page_shows_title_in_selected_language_and_start_form(client):
    run = open_quiz_run(locales=("cs", "uk"))
    html = text(client.get("/q/kviz?lang=uk"))
    assert '<html lang="uk"' in html
    assert "Název uk" in html
    assert f'action="/r/{run.id}/start"' in html
    assert f'hx-post="/r/{run.id}/start"' in html
    assert 'name="lang" value="uk"' in html
    assert "Otázka" not in html


def test_quiz_page_offers_only_published_locales(client):
    open_quiz_run(locales=("cs", "uk"))
    html = text(client.get("/q/kviz"))
    assert "?lang=uk" in html and "?lang=cs" in html
    assert "?lang=en" not in html


@pytest.mark.parametrize("query", ["?lang=de", "?lang=en"])
def test_quiz_page_falls_back_for_unsupported_lang(client, query):
    open_quiz_run(locales=("cs", "uk"))
    response = client.get(f"/q/kviz{query}")
    assert response.status_code == 200
    assert '<html lang="cs"' in text(response)
    assert "Název cs" in text(response)


def test_unknown_slug_is_themed_404(client):
    response = client.get("/q/neni")
    assert response.status_code == 404
    assert "Kvízotron" in text(response)
    assert "Tento kvíz neexistuje." in text(response)


def test_quiz_without_open_run_says_not_running(client):
    published_quiz()
    response = client.get("/q/kviz")
    assert response.status_code == 404
    assert "Tento kvíz teď neběží." in text(response)


def test_quiz_never_published_says_not_running(client):
    make_quiz()
    assert "Tento kvíz teď neběží." in text(client.get("/q/kviz"))


def test_specific_run_page_of_open_run_works(client):
    run = open_quiz_run()
    response = client.get(f"/q/kviz/r/{run.id}")
    assert response.status_code == 200
    assert f'action="/r/{run.id}/start"' in text(response)


def test_run_of_other_quiz_is_404(client):
    run = open_quiz_run("prvni")
    open_quiz_run("druhy")
    assert client.get(f"/q/druhy/r/{run.id}").status_code == 404


def test_malformed_run_id_is_404(client):
    open_quiz_run()
    assert client.get("/q/kviz/r/nonsense").status_code == 404


def test_closed_run_page_is_view_only(client):
    run = open_quiz_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    response = client.get(f"/q/kviz/r/{run.id}")
    assert response.status_code == 200
    assert "Tento běh skončil." in text(response)
    assert "/start" not in text(response)


def test_page_uses_revision_title_not_later_quiz_edit(client):
    run = open_quiz_run()
    quiz = run.quiz
    quiz.title = {"cs": "Rozepsaný název"}
    quiz.save()
    html = text(client.get("/q/kviz"))
    assert "Název cs" in html and "Rozepsaný" not in html
    assert "Rozepsaný" not in text(client.get("/"))


def test_title_markup_is_escaped(client):
    run = open_quiz_run()
    revision = run.current_revision
    snapshot = revision.snapshot_json
    snapshot["title"]["cs"] = "<script>x"
    type(revision).objects.filter(pk=revision.pk).update(snapshot_json=snapshot)
    for url in ("/", "/q/kviz"):
        html = text(client.get(url))
        assert "<script>x" not in html and "&lt;script&gt;x" in html


def started_page(client, quiz):
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    return text(client.post(f"/r/{run.id}/start", {"lang": "cs"}))


def quiz_with_trick_question():
    quiz = make_quiz()
    standard = add_question(quiz)
    config = definition(quiz.supported_locales)
    config["correct"] = []
    trick = authoring.save_question(quiz, None, "choice", config)
    return quiz, standard, trick


def test_none_option_all_questions_appears_on_a_standard_question(client):
    quiz, standard, trick = quiz_with_trick_question()
    html = started_page(client, quiz)
    assert f'name="{standard}:options[]" value="none"' in html
    assert f'name="{trick}:options[]" value="none"' in html


def test_none_option_trick_questions_appears_only_on_trick(client):
    quiz, standard, trick = quiz_with_trick_question()
    settings.set_override(
        settings.NONE_OPTION, quiz, settings.NoneOption.TRICK_QUESTIONS, admin_id=ADMIN_ID
    )
    html = started_page(client, quiz)
    assert f'name="{standard}:options[]" value="none"' not in html
    assert f'name="{trick}:options[]" value="none"' in html


def test_texts_of_a_question_type_follow_the_language_of_the_attempt(client):
    quiz = make_quiz(locales=("cs", "uk"))
    add_question(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(
        client.post(
            f"/r/{run.id}/start",
            {"lang": "uk"},
            headers={"HX-Request": "true", "Accept-Language": "en"},
        )
    )
    assert "Жодна з відповідей" in html


def test_landing_links_to_the_administration(client):
    html = text(client.get("/?lang=uk"))
    assert '<a href="/admin/quizzes?lang=uk">Адміністрування</a>' in html
    assert "/admin/" not in text(client.get("/about?lang=uk"))

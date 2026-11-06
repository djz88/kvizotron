import pytest
from django.test import Client

from app.domain.models import Quiz, QuizRevision
from app.kernel.models import PluginInstallation
from tests.domain.helpers import add_question, make_quiz, published_quiz

pytestmark = pytest.mark.django_db
QUESTION = {"prompt_cs": "Otázka", "option_0_cs": "A", "option_1_cs": "B", "correct": "1"}


def create(client, **fields):
    data = {
        "slug": "kviz",
        "supported_locales": ["cs"],
        "default_locale": "cs",
        "title_cs": "Název",
    }
    return client.post("/admin/quizzes/new", data | fields)


def edit_url(quiz):
    return f"/admin/quizzes/{quiz.id}/edit"


def text(response):
    return response.content.decode()


def test_create_quiz_opens_editor(logged_in):
    response = create(logged_in, featured="on")
    quiz = Quiz.objects.get()
    assert response["Location"] == edit_url(quiz)
    assert quiz.title == {"cs": "Název"}
    assert quiz.featured is True


@pytest.mark.parametrize("slug", ["", "s mezerou", "háček", "x" * 81])
def test_create_quiz_with_invalid_slug_shows_error(logged_in, slug):
    response = create(logged_in, slug=slug)
    assert response.status_code == 200
    assert "errorlist" in text(response)
    assert not Quiz.objects.exists()


def test_duplicate_slug_shows_error(logged_in):
    make_quiz("kviz")
    response = create(logged_in)
    assert response.status_code == 200
    assert "Tento identifikátor už používá jiný kvíz." in text(response)


def test_default_locale_must_be_selected(logged_in):
    response = create(logged_in, default_locale="uk")
    assert "Výchozí jazyk musí být mezi vybranými jazyky." in text(response)
    assert not Quiz.objects.exists()


def test_no_locale_selected_is_refused(logged_in):
    assert "errorlist" in text(create(logged_in, supported_locales=[]))
    assert not Quiz.objects.exists()


def test_unknown_locale_is_refused(logged_in):
    assert "errorlist" in text(create(logged_in, supported_locales=["de"]))
    assert not Quiz.objects.exists()


def test_quiz_title_is_escaped_in_list(logged_in):
    create(logged_in, title_cs="<script>x")
    html = text(logged_in.get("/admin/quizzes"))
    assert "<script>x" not in html and "&lt;script&gt;x" in html


def test_unknown_quiz_is_404(logged_in):
    assert (
        logged_in.get("/admin/quizzes/0190a0a0-0000-7000-8000-000000000000/edit").status_code == 404
    )


def test_add_edit_delete_question_through_plugin_form(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice.single"
    assert 'name="prompt_cs"' in text(logged_in.get(url))

    assert logged_in.post(url, QUESTION)["Location"] == edit_url(quiz)
    draft = quiz.revisions.get(status="DRAFT")
    question = draft.snapshot_json["questions"][0]
    assert question["definition"]["prompt"] == {"cs": "Otázka"}
    assert "Otázka" in text(logged_in.get(edit_url(quiz)))

    url = f"/admin/quizzes/{quiz.id}/questions/{question['id']}/edit"
    assert 'value="Otázka"' in text(logged_in.get(url))
    logged_in.post(url, QUESTION | {"prompt_cs": "Změna"})
    draft.refresh_from_db()
    assert draft.snapshot_json["questions"][0]["definition"]["prompt"] == {"cs": "Změna"}

    url = f"/admin/quizzes/{quiz.id}/questions/{question['id']}/delete"
    assert logged_in.get(url).status_code == 405
    assert logged_in.post(url)["Location"] == edit_url(quiz)
    draft.refresh_from_db()
    assert draft.snapshot_json["questions"] == []


def test_edit_of_unknown_question_is_404(logged_in):
    quiz = make_quiz()
    assert logged_in.get(f"/admin/quizzes/{quiz.id}/questions/nope/edit").status_code == 404
    assert logged_in.post(f"/admin/quizzes/{quiz.id}/questions/nope/delete").status_code == 404


@pytest.mark.parametrize("query", ["?type=no.such", ""])
def test_new_question_with_unknown_type_is_404(logged_in, query):
    assert logged_in.get(f"/admin/quizzes/{make_quiz().id}/questions/new{query}").status_code == 404


def disable_choice_single():
    PluginInstallation.objects.update_or_create(
        pk="question.choice_single",
        defaults={"version": "1.0.0", "manifest_json": {}, "enabled": False},
    )


def test_new_question_with_disabled_type_is_404(logged_in):
    quiz = make_quiz()
    disable_choice_single()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice.single"
    assert logged_in.get(url).status_code == 404


def test_editor_offers_only_enabled_question_types(logged_in):
    quiz = make_quiz()
    assert "type=choice.single" in text(logged_in.get(edit_url(quiz)))
    disable_choice_single()
    assert "type=choice.single" not in text(logged_in.get(edit_url(quiz)))


def test_invalid_question_form_keeps_input_and_shows_error(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice.single"
    response = logged_in.post(url, QUESTION | {"correct": "5"})
    assert response.status_code == 200
    assert 'value="Otázka"' in text(response)
    assert "Choose the correct option" in text(response)
    assert not quiz.revisions.exists()


def test_publish_failure_lists_question_and_language(logged_in):
    quiz = make_quiz(locales=("cs", "uk"))
    add_question(quiz)
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice.single"
    logged_in.post(url, QUESTION)  # filled in Czech only
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/publish")
    assert response.status_code == 200
    assert "Otázka 2, jazyk uk" in text(response)
    assert not quiz.revisions.filter(status="PUBLISHED").exists()


def test_publish_without_questions_says_so(logged_in):
    response = logged_in.post(f"/admin/quizzes/{make_quiz().id}/publish")
    assert "Kvíz nemá žádnou otázku." in text(response)


def test_publish_success_shows_published_state(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/publish")
    assert response["Location"] == edit_url(quiz)
    assert "Publikovaná revize: 1" in text(logged_in.get(edit_url(quiz)))
    assert "Publikovaná revize: 1" in text(logged_in.get("/admin/quizzes"))


def test_publish_get_is_405(logged_in):
    assert logged_in.get(f"/admin/quizzes/{make_quiz().id}/publish").status_code == 405


def test_edit_after_publication_leaves_published_revision_unchanged(logged_in):
    quiz = published_quiz()
    published = quiz.revisions.get()
    frozen = published.snapshot_json
    question = frozen["questions"][0]
    url = f"/admin/quizzes/{quiz.id}/questions/{question['id']}/edit"
    logged_in.post(url, QUESTION | {"prompt_cs": "Změna"})
    published.refresh_from_db()
    assert published.snapshot_json == frozen
    assert quiz.revisions.get(status=QuizRevision.Status.DRAFT).revision_no == 2
    assert "Změna" in text(logged_in.get(edit_url(quiz)))


def post_quiz(client, quiz, **fields):
    data = {
        "slug": quiz.slug,
        "supported_locales": quiz.supported_locales,
        "default_locale": quiz.default_locale,
        "title_cs": "Název cs",
    }
    return client.post(edit_url(quiz), data | fields)


def test_quiz_change_after_publication_can_be_published(logged_in):
    quiz = published_quiz()
    assert post_quiz(logged_in, quiz, title_cs="Nový")["Location"] == edit_url(quiz)
    assert logged_in.post(f"/admin/quizzes/{quiz.id}/publish").status_code == 302
    assert quiz.revisions.get(status="PUBLISHED").snapshot_json["title"]["cs"] == "Nový"


def test_slug_can_change_before_first_publication(logged_in):
    quiz = make_quiz("stary")
    post_quiz(logged_in, quiz, slug="novy")
    quiz.refresh_from_db()
    assert quiz.slug == "novy"


def test_slug_cannot_change_after_first_publication(logged_in):
    quiz = published_quiz("stary")
    post_quiz(logged_in, quiz, slug="novy")
    quiz.refresh_from_db()
    assert quiz.slug == "stary"


def test_featured_flag_is_saved_and_cleared(logged_in):
    quiz = make_quiz()
    post_quiz(logged_in, quiz, featured="on")
    quiz.refresh_from_db()
    assert quiz.featured is True
    post_quiz(logged_in, quiz)
    quiz.refresh_from_db()
    assert quiz.featured is False


@pytest.mark.parametrize("suffix", ["publish", "runs", "questions/x/delete"])
def test_state_change_without_csrf_token_is_403(admin_user, suffix):
    quiz = make_quiz()
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)
    assert client.post(f"/admin/quizzes/{quiz.id}/{suffix}").status_code == 403


def test_forms_carry_csrf_token(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    assert "csrfmiddlewaretoken" in text(logged_in.get(edit_url(quiz)))
    assert "csrfmiddlewaretoken" in text(logged_in.get("/admin/quizzes/new"))


def test_settings_form_after_failed_publish_goes_to_the_editor(logged_in):
    quiz = make_quiz()
    quiz.title = {}
    quiz.save()
    html = text(logged_in.post(f"/admin/quizzes/{quiz.id}/publish"))
    assert f'<form method="post" action="{edit_url(quiz)}">' in html


def test_settings_form_after_refused_run_goes_to_the_editor(logged_in):
    quiz = make_quiz()
    html = text(logged_in.post(f"/admin/quizzes/{quiz.id}/runs"))
    assert f'<form method="post" action="{edit_url(quiz)}">' in html


def test_language_link_keeps_the_question_type(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice.single"
    html = text(logged_in.get(url))
    assert 'href="?type=choice.single&amp;lang=en"' in html
    assert logged_in.get(f"{url}&lang=en").status_code == 200


def test_language_link_after_a_refused_post_leads_to_a_working_page(logged_in):
    quiz = make_quiz()
    html = text(logged_in.post(f"/admin/quizzes/{quiz.id}/publish"))
    assert 'href="/admin/quizzes?lang=en"' in html

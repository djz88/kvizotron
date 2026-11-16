import io
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import translation
from PIL import Image

from app.api.admin_forms import conflict_messages, result_messages
from app.contracts import SCOREBOARD_VISIBILITY
from app.domain import authoring, data_policy, results, rewards, settings
from app.domain.models import Quiz, QuizRevision, QuizRun
from app.kernel.models import PluginInstallation
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_B,
    add_question,
    make_quiz,
    open_quiz_run,
    published_quiz,
)
from tests.support.client import FormClient
from tests.support.requirements import REASON

pytestmark = pytest.mark.django_db
QUESTION = {"prompt_cs": "Otázka", "option_0_cs": "A", "option_1_cs": "B", "correct_1": "on"}


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


@pytest.mark.parametrize("slug", ["s mezerou", "háček", "x" * 81])
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
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice"
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


def disable_choice():
    PluginInstallation.objects.update_or_create(
        pk="question.choice",
        defaults={"version": "1.0.0", "manifest_json": {}, "enabled": False},
    )


def test_new_question_with_disabled_type_is_404(logged_in):
    quiz = make_quiz()
    disable_choice()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice"
    assert logged_in.get(url).status_code == 404


def test_editor_offers_only_enabled_question_types(logged_in):
    quiz = make_quiz()
    assert "type=choice" in text(logged_in.get(edit_url(quiz)))
    disable_choice()
    assert "type=choice" not in text(logged_in.get(edit_url(quiz)))


def test_invalid_question_form_keeps_input_and_shows_error(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice"
    response = logged_in.post(url, QUESTION | {"correct_5": "on"})
    assert response.status_code == 200
    assert 'value="Otázka"' in text(response)
    assert "označený jako správný nemá text" in text(response)
    assert not quiz.revisions.exists()


def test_publish_failure_lists_question_and_language(logged_in):
    quiz = make_quiz(locales=("cs", "uk"))
    add_question(quiz)
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice"
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
    response = publish_via_page(logged_in, quiz)
    assert response["Location"] == edit_url(quiz)
    assert "Publikovaná revize: 1" in text(logged_in.get(edit_url(quiz)))
    assert "Publikovaná revize: 1" in text(logged_in.get("/admin/quizzes"))


def publish_via_page(client, quiz, **fields):
    url = f"/admin/quizzes/{quiz.id}/publish"
    page = text(client.get(url))
    found = re.search(r'name="snapshot_hash" value="([^"]*)"', page).group(1)
    return client.post(url, {"snapshot_hash": found, **fields})


def test_publish_page_shows_changes(logged_in):
    quiz = published_quiz()
    add_question(quiz, OPTION_B, question_id=authoring.editable_questions(quiz)[0]["id"])
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/publish?lang=en"))
    assert "1: Ano cs" in html and "2: Ne cs" in html
    assert not quiz.revisions.filter(status="DRAFT", published_at__isnull=False).exists()


def test_publish_page_lists_problems_and_offers_no_button(logged_in):
    html = text(logged_in.get(f"/admin/quizzes/{make_quiz().id}/publish"))
    assert "Kvíz nemá žádnou otázku." in html
    assert "snapshot_hash" not in html


def test_publish_page_says_when_there_is_nothing_new(logged_in):
    html = text(logged_in.get(f"/admin/quizzes/{published_quiz().id}/publish"))
    assert "snapshot_hash" not in html


def test_publish_page_offers_three_choices_with_let_finish_preselected_when_policy_is_ask(
    logged_in,
):
    run = open_quiz_run()
    add_question(run.quiz, OPTION_B, question_id=authoring.editable_questions(run.quiz)[0]["id"])
    html = text(logged_in.get(f"/admin/quizzes/{run.quiz.id}/publish"))
    assert 'value="notify_switch"' in html and 'value="stay"' in html
    assert 'value="let_finish" checked' in html


def test_publish_page_states_outcome_for_stored_policy(logged_in):
    run = open_quiz_run()
    settings.set_override(settings.REVISION_SWITCH_POLICY, run.quiz, "notify_switch", admin_id=None)
    add_question(run.quiz, OPTION_B, question_id=authoring.editable_questions(run.quiz)[0]["id"])
    html = text(logged_in.get(f"/admin/quizzes/{run.quiz.id}/publish?lang=en"))
    assert 'name="decision"' not in html
    assert "notice" in html


def test_publish_page_offers_nothing_without_open_round(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    assert 'name="decision"' not in text(logged_in.get(f"/admin/quizzes/{quiz.id}/publish"))


def test_publish_decision_reaches_the_round(logged_in):
    run = open_quiz_run()
    add_question(run.quiz, OPTION_B, question_id=authoring.editable_questions(run.quiz)[0]["id"])
    assert publish_via_page(logged_in, run.quiz, decision="notify_switch").status_code == 302
    run.refresh_from_db()
    assert run.current_row().switch_mode == "switch"


def test_post_with_stale_hash_shows_page_and_publishes_nothing(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/publish", {"snapshot_hash": "old"})
    assert response.status_code == 200
    assert "snapshot_hash" in text(response) and 'role="alert"' in text(response)
    assert not quiz.revisions.filter(status="PUBLISHED").exists()


def test_post_without_decision_under_ask_shows_page_with_message(logged_in):
    run = open_quiz_run()
    add_question(run.quiz, OPTION_B, question_id=authoring.editable_questions(run.quiz)[0]["id"])
    response = publish_via_page(logged_in, run.quiz)
    assert response.status_code == 200 and 'role="alert"' in text(response)
    assert run.quiz.revisions.filter(status="DRAFT").exists()


def test_overview_escapes_markup(logged_in):
    quiz = make_quiz()
    quiz.title = {"cs": "<script>titul"}
    quiz.save()
    add_question(quiz, prompt="<script>otazka")
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/publish"))
    assert "<script>titul" not in html and "<script>otazka" not in html
    assert "&lt;script&gt;otazka" in html


def test_overview_renders_with_uninstalled_type(logged_in):
    quiz = published_quiz()
    draft = authoring.get_draft(quiz)
    draft.snapshot_json["questions"][0]["type"] = "gone.type"
    draft.save()
    response = logged_in.get(f"/admin/quizzes/{quiz.id}/publish")
    assert response.status_code == 200 and "gone.type" in text(response)


def test_edit_page_links_to_publish_page(logged_in):
    quiz = make_quiz()
    html = text(logged_in.get(edit_url(quiz)))
    assert f'href="/admin/quizzes/{quiz.id}/publish?start=1"' in html


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
        "description_cs": "Popis cs",
    }
    return client.post(edit_url(quiz), data | fields)


def test_quiz_change_after_publication_can_be_published(logged_in):
    quiz = published_quiz()
    assert post_quiz(logged_in, quiz, title_cs="Nový")["Location"] == (
        f"/admin/quizzes/{quiz.id}/settings"
    )
    assert publish_via_page(logged_in, quiz).status_code == 302
    assert quiz.revisions.get(status="PUBLISHED").snapshot_json["title"]["cs"] == "Nový"


def test_slug_can_change_before_first_publication(logged_in):
    quiz = make_quiz("stary")
    logged_in.post(f"/admin/quizzes/{quiz.id}/settings", {"slug": "novy"})
    quiz.refresh_from_db()
    assert quiz.slug == "novy"


def test_slug_cannot_change_after_first_publication(logged_in):
    quiz = published_quiz("stary")
    post_quiz(logged_in, quiz, slug="novy")
    quiz.refresh_from_db()
    assert quiz.slug == "stary"


def test_featured_flag_is_saved_and_cleared(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/settings"
    logged_in.post(url, {"slug": quiz.slug, "featured": "on"})
    quiz.refresh_from_db()
    assert quiz.featured is True
    logged_in.post(url, {"slug": quiz.slug})
    quiz.refresh_from_db()
    assert quiz.featured is False


@pytest.mark.parametrize("suffix", ["publish", "runs", "questions/x/delete"])
def test_state_change_without_csrf_token_is_403(admin_user, suffix):
    quiz = make_quiz()
    client = FormClient(enforce_csrf_checks=True)
    client.force_login(admin_user)
    assert client.post(f"/admin/quizzes/{quiz.id}/{suffix}").status_code == 403


def test_forms_carry_csrf_token(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    assert "csrfmiddlewaretoken" in text(logged_in.get(edit_url(quiz)))
    assert "csrfmiddlewaretoken" in text(logged_in.get("/admin/quizzes/new"))


def test_failed_publish_links_back_to_the_editor(logged_in):
    quiz = make_quiz()
    quiz.title = {}
    quiz.save()
    html = text(logged_in.post(f"/admin/quizzes/{quiz.id}/publish"))
    assert f'href="{edit_url(quiz)}"' in html


def test_refused_run_returns_to_the_questions_tab_with_the_reason(logged_in):
    quiz = make_quiz()
    html = text(logged_in.post(f"/admin/quizzes/{quiz.id}/runs?lang=en"))
    assert f'<a href="{edit_url(quiz)}" aria-current="page">' in html
    assert "Publish the quiz first." in html


def test_language_link_keeps_the_question_type(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice"
    html = text(logged_in.get(url))
    assert 'href="?type=choice&amp;lang=en"' in html
    assert logged_in.get(f"{url}&lang=en").status_code == 200


def test_language_link_after_a_refused_post_leads_to_a_working_page(logged_in):
    quiz = make_quiz()
    html = text(logged_in.post(f"/admin/quizzes/{quiz.id}/publish"))
    assert 'href="/admin/quizzes?lang=en"' in html


def test_duplicate_options_keep_input_and_show_a_message(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice&lang=en"
    form = QUESTION | {"option_0_cs": "Stejně", "option_1_cs": "stejně"}
    response = logged_in.post(url, form)
    html = text(response)
    assert response.status_code == 200
    assert 'role="alert"' in html and "the same text" in html
    assert 'value="stejně"' in html
    assert authoring.editable_questions(quiz) == []


def test_duplicate_options_message_is_in_the_admin_language(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice&lang=cs"
    html = text(logged_in.post(url, QUESTION | {"option_0_cs": "Stejně", "option_1_cs": "stejně"}))
    assert "Dvě odpovědi mají stejný text" in html


def test_publication_page_names_the_duplicate(logged_in):
    quiz = make_quiz()
    config = {
        "prompt": {"cs": "Otázka"},
        "options": [
            {"id": "a", "text": {"cs": "Stejně"}},
            {"id": "b", "text": {"cs": "stejně"}},
        ],
        "correct": ["a"],
    }
    authoring.save_question(quiz, None, "choice", config)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/publish?lang=en"))
    assert "Two options have the same text" in html


def test_yes_no_preset_opens_a_prefilled_form_and_saves(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice&preset=yes_no"
    assert 'value="Ano"' in text(logged_in.get(url))
    form = {
        "kind": "yes_no",
        "prompt_cs": "Je to pravda?",
        "option_0_cs": "Ano",
        "option_1_cs": "Ne",
        "correct_1": "on",
    }
    assert logged_in.post(url, form).status_code == 302
    saved = authoring.editable_questions(quiz)[0]["definition"]
    assert saved["kind"] == "yes_no" and saved["correct"] == [saved["options"][1]["id"]]


def test_unknown_preset_opens_an_empty_form(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice&preset=nope"
    assert logged_in.get(url).status_code == 200


@pytest.fixture
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


@pytest.fixture
def uploader(admin_user, media_path):
    """A browser sends this form as multipart; FormClient does not."""
    client = Client()
    client.force_login(admin_user)
    return client


def png(name="fotka.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 10, 10)).save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


IMAGE_QUESTION = {
    "prompt_cs": "Kdo je na fotce?",
    "image_alt_cs": "Fotka muže",
    "option_0_cs": "A",
    "option_1_cs": "B",
    "correct_0": "on",
}


def new_question_url(quiz):
    return f"/admin/quizzes/{quiz.id}/questions/new?type=choice"


def saved_definition(quiz):
    return authoring.editable_questions(quiz)[0]["definition"]


def test_question_form_is_multipart(logged_in):
    assert 'enctype="multipart/form-data"' in text(logged_in.get(new_question_url(make_quiz())))


def test_upload_with_the_question_stores_and_references_the_image(uploader):
    quiz = make_quiz()
    response = uploader.post(new_question_url(quiz), IMAGE_QUESTION | {"image": png()})
    assert response.status_code == 302
    saved = saved_definition(quiz)["image"]
    assert saved["alt"] == {"cs": "Fotka muže"}
    assert uploader.get(f"/media/{saved['asset']}")["Content-Type"] == "image/webp"


def test_upload_on_an_answer_with_only_an_image(uploader):
    quiz = make_quiz()
    form = IMAGE_QUESTION | {
        "option_1_cs": "",
        "option_1_image": png(),
        "option_1_image_alt_cs": "Popis",
    }
    assert uploader.post(new_question_url(quiz), form).status_code == 302
    assert saved_definition(quiz)["options"][1]["image"]["alt"] == {"cs": "Popis"}


def test_failed_validation_keeps_the_uploaded_image(uploader):
    quiz = make_quiz()
    form = IMAGE_QUESTION | {"image": png(), "option_1_cs": "A"}  # two options alike
    response = uploader.post(new_question_url(quiz), form)
    assert response.status_code == 200
    html = text(response)
    assert not quiz.revisions.exists()
    asset = re.search(r'name="image_asset" value="([^"]+)"', html).group(1)
    assert f'<img src="/media/{asset}"' in html
    form = IMAGE_QUESTION | {"image_asset": asset}  # sent again without choosing the file
    assert uploader.post(new_question_url(quiz), form).status_code == 302
    assert saved_definition(quiz)["image"]["asset"] == asset


def test_refused_file_shows_the_message_and_keeps_other_fields(uploader):
    quiz = make_quiz()
    fake = SimpleUploadedFile("fotka.png", b"this is not an image", content_type="image/png")
    response = uploader.post(new_question_url(quiz), IMAGE_QUESTION | {"image": fake})
    assert response.status_code == 200
    html = text(response)
    assert "není použitelný obrázek" in html
    assert 'value="Kdo je na fotce?"' in html
    assert not quiz.revisions.exists()


def test_a_forged_asset_id_is_ignored(uploader):
    quiz = make_quiz()
    form = IMAGE_QUESTION | {"image_asset": "00000000-0000-7000-8000-000000000000"}
    assert uploader.post(new_question_url(quiz), form).status_code == 302
    assert "image" not in saved_definition(quiz)


def test_a_new_file_beats_the_remove_box(uploader):
    quiz = make_quiz()
    form = IMAGE_QUESTION | {"image": png(), "image_remove": "on"}
    assert uploader.post(new_question_url(quiz), form).status_code == 302
    assert "image" in saved_definition(quiz)


def test_missing_alternative_text_blocks_publication(uploader):
    quiz = make_quiz()
    form = IMAGE_QUESTION | {"image": png(), "image_alt_cs": ""}
    assert uploader.post(new_question_url(quiz), form).status_code == 302
    problems = authoring.validate_for_publication(quiz)
    assert any(problem.question_no == 1 for problem in problems)


def test_language_added_later_needs_an_alternative_text(uploader):
    quiz = make_quiz()
    response = uploader.post(new_question_url(quiz), IMAGE_QUESTION | {"image": png()})
    assert response.status_code == 302
    assert not authoring.validate_for_publication(quiz)
    quiz.supported_locales = ["cs", "en"]
    quiz.title["en"] = quiz.description["en"] = "x"
    quiz.save()
    definition = saved_definition(quiz)
    definition["prompt"]["en"] = "Q"
    for option in definition["options"]:
        option["text"]["en"] = option["text"]["cs"]
    question_id = authoring.editable_questions(quiz)[0]["id"]
    authoring.save_question(quiz, question_id, "choice", definition)
    problems = authoring.validate_for_publication(quiz)
    assert [problem.locale for problem in problems] == ["en"]


def test_public_page_shows_image_with_alt_in_the_chosen_language(uploader):
    quiz = make_quiz(locales=("cs", "en"))
    form = IMAGE_QUESTION | {
        "image": png(),
        "image_alt_en": "A photo",
        "prompt_en": "Who?",
        "option_0_en": "A",
        "option_1_en": "B",
    }
    assert uploader.post(new_question_url(quiz), form).status_code == 302
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(FormClient().post(f"/r/{run.id}/start", {"lang": "en"}))
    asset = saved_definition(quiz)["image"]["asset"]
    assert f'<img src="/media/{asset}" alt="A photo" loading="lazy"' in html
    assert html.count(asset) == 1  # only inside the address


def test_published_revision_keeps_its_image_after_the_draft_removes_it(uploader):
    quiz = make_quiz()
    response = uploader.post(new_question_url(quiz), IMAGE_QUESTION | {"image": png()})
    assert response.status_code == 302
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    definition = saved_definition(quiz)
    asset = definition["image"]["asset"]
    question_id = authoring.editable_questions(quiz)[0]["id"]
    del definition["image"]
    authoring.save_question(quiz, question_id, "choice", definition)
    html = text(FormClient().post(f"/r/{run.id}/start", {"lang": "cs"}))
    assert f'<img src="/media/{asset}"' in html
    assert uploader.get(f"/media/{asset}").status_code == 200


def test_change_of_image_shows_in_the_overview(uploader):
    quiz = make_quiz()
    response = uploader.post(new_question_url(quiz), IMAGE_QUESTION | {"image": png()})
    assert response.status_code == 302
    authoring.publish(quiz, admin_id=ADMIN_ID)
    question_id = authoring.editable_questions(quiz)[0]["id"]
    edit = f"/admin/quizzes/{quiz.id}/questions/{question_id}/edit"
    current = saved_definition(quiz)
    form = {
        "prompt_cs": current["prompt"]["cs"],
        "image": png("jina.png"),
        "image_alt_cs": "Jiný popis",
    }
    for row, option in enumerate(current["options"]):
        form |= {f"option_{row}_id": option["id"], f"option_{row}_cs": option["text"]["cs"]}
    form["correct_0"] = "on"
    assert uploader.post(edit, form).status_code == 302
    assert "Jiný popis" in text(uploader.get(f"/admin/quizzes/{quiz.id}/publish"))


def test_refused_file_keeps_its_description_and_its_row(uploader):
    quiz = make_quiz()
    fake = SimpleUploadedFile("fotka.png", b"this is not an image", content_type="image/png")
    form = IMAGE_QUESTION | {
        "option_0_cs": "",
        "option_0_image": fake,
        "option_0_image_alt_cs": "Můj popis",
        "correct_0": "",
    }
    html = text(uploader.post(new_question_url(quiz), form))
    assert 'name="option_0_image_alt_cs" value="Můj popis"' in html
    assert 'name="option_1_cs" value="B"' in html
    assert not quiz.revisions.exists()


def test_several_correct_without_several_answers_keeps_the_form_with_a_message(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice"
    response = logged_in.post(url, QUESTION | {"correct_0": "on"})
    assert response.status_code == 200
    assert 'name="correct_0" checked' in text(response)
    assert "více odpovědí" in text(response)
    assert not quiz.revisions.exists()


def _refuse_open(monkeypatch, error):
    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(authoring, "open_run", refuse)


def _refuse_start(monkeypatch, error):
    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(authoring, "publish_and_open", refuse)


def test_start_from_publish_page_refuses_an_unmet_requirement(logged_in, monkeypatch):
    # Not reachable with a natural setup: publication validation checks the same requirement
    # first and refuses before the run opens, so the refusal is raised by a stub here.
    quiz = make_quiz()
    add_question(quiz)
    _refuse_start(monkeypatch, authoring.RequirementUnmet([REASON]))
    response = publish_via_page(logged_in, quiz, start="1")
    assert response.status_code == 200
    assert REASON in text(response)
    assert not QuizRun.objects.exists()


def test_start_from_publish_page_refuses_a_reward_conflict(logged_in, monkeypatch):
    quiz = make_quiz()
    add_question(quiz)
    _refuse_start(monkeypatch, rewards.RewardConflict(["profile"]))
    response = publish_via_page(logged_in, quiz, start="1")
    assert response.status_code == 200
    with translation.override("cs"):
        assert rewards.messages(["profile"])[0] in text(response)
    assert not QuizRun.objects.exists()


def test_start_from_publish_page_refuses_a_stateless_conflict(logged_in, monkeypatch):
    quiz = make_quiz()
    add_question(quiz)
    _refuse_start(monkeypatch, data_policy.StatelessConflict(["photo_question"]))
    response = publish_via_page(logged_in, quiz, start="1")
    assert response.status_code == 200
    with translation.override("cs"):
        assert conflict_messages(["photo_question"])[0] in text(response)
    assert not QuizRun.objects.exists()


def test_two_starts_open_one_run(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    first = publish_via_page(logged_in, quiz, start="1")
    assert first.status_code == 302
    second = logged_in.post(f"/admin/quizzes/{quiz.id}/runs")
    assert second.status_code == 200
    assert "Tento kvíz už má probíhající běh." in text(second)
    assert QuizRun.objects.count() == 1


def scoreboard_quiz(published=False):
    """Answers are not kept but the scoreboard is shown: opening refuses with ResultConflict."""
    quiz = published_quiz() if published else make_quiz()
    if not published:
        add_question(quiz)
    settings.set_override(settings.DATA_PROFILE, quiz, "none", admin_id=ADMIN_ID)
    settings.set_override(SCOREBOARD_VISIBILITY, quiz, "live", admin_id=ADMIN_ID)
    return quiz


def test_start_from_publish_page_refuses_a_real_result_conflict(logged_in):
    quiz = scoreboard_quiz()
    response = publish_via_page(logged_in, quiz, start="1")
    assert response.status_code == 200
    with translation.override("cs"):
        assert result_messages([results.STATELESS])[0] in text(response)
    assert not QuizRun.objects.exists()
    assert not quiz.revisions.filter(published_at__isnull=False).exists()


def test_open_run_refuses_a_real_result_conflict(logged_in):
    quiz = scoreboard_quiz(published=True)
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/runs")
    assert response.status_code == 200
    with translation.override("cs"):
        assert result_messages([results.STATELESS])[0] in text(response)
    assert not QuizRun.objects.exists()


def test_new_quiz_without_slug_derives_it_from_the_name(logged_in):
    response = logged_in.post(
        "/admin/quizzes/new",
        {"supported_locales": ["cs"], "default_locale": "cs", "title_cs": "Vánoční kvíz 2026"},
    )
    assert response.status_code == 302
    assert Quiz.objects.get().slug == "vanocni-kviz-2026"


def test_a_derived_slug_that_is_taken_gets_a_number(logged_in):
    """Different titles may still give one address; two quizzes never share a title."""
    fields = {"supported_locales": ["cs"], "default_locale": "cs"}
    for title in ("Vánoční kvíz", "Vánoční kvíz!", "Vánoční  kvíz?"):
        response = logged_in.post("/admin/quizzes/new", fields | {"title_cs": title})
        assert response.status_code == 302
    assert sorted(Quiz.objects.values_list("slug", flat=True)) == [
        "vanocni-kviz",
        "vanocni-kviz-2",
        "vanocni-kviz-3",
    ]


def test_new_quiz_with_a_whitespace_name_shows_the_name_error(logged_in):
    response = logged_in.post(
        "/admin/quizzes/new",
        {"supported_locales": ["cs"], "default_locale": "cs", "title_cs": "   "},
    )
    assert response.status_code == 200
    assert "Zadejte název" in response.content.decode()
    assert not Quiz.objects.exists()


def test_new_quiz_form_preselects_the_default_language(logged_in):
    html = logged_in.get("/admin/quizzes/new").content.decode()
    assert re.search(r'<input[^>]*value="cs"[^>]*checked|<input[^>]*checked[^>]*value="cs"', html)
    assert not re.search(r'value="en"[^>]*checked|checked[^>]*value="en"', html)
    assert "Čeština" in html and "English" in html and "Українська" in html


def test_new_quiz_form_shows_the_quiz_type_open(logged_in):
    html = logged_in.get("/admin/quizzes/new").content.decode()
    assert '<details class="quiz-type-choice" open>' in html


@pytest.mark.parametrize("title", ["Вікторина", "???"])
def test_a_name_that_gives_no_address_asks_for_the_slug(logged_in, title):
    response = logged_in.post(
        "/admin/quizzes/new",
        {"supported_locales": ["cs"], "default_locale": "cs", "title_cs": title},
    )
    assert response.status_code == 200
    html = response.content.decode()
    message = "Z tohoto názvu nejde udělat adresa. Vyplňte identifikátor v adrese."
    assert f"<li>{message}</li>" in html
    after = html[html.index(message) :]
    assert re.search(r'name="(\w+)"', after).group(1) == "slug"  # the next input is the slug's
    assert "Zadejte název" not in html
    assert not Quiz.objects.exists()


def test_an_empty_name_asks_for_the_title_on_the_title_field(logged_in):
    response = logged_in.post(
        "/admin/quizzes/new",
        {"supported_locales": ["cs"], "default_locale": "cs", "title_cs": ""},
    )
    html = response.content.decode()
    message = "Zadejte název, nebo místo něj adresu (identifikátor v URL)."
    assert f"<li>{message}</li>" in html
    after = html[html.index(message) :]
    assert re.search(r'name="(\w+)"', after).group(1) == "title_cs"
    assert "nejde udělat adresa" not in html
    assert not Quiz.objects.exists()


def test_first_publication_shows_a_summary_not_a_diff(logged_in):
    quiz = make_quiz(locales=("cs", "uk"))
    for _ in range(3):
        add_question(quiz)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/publish?lang=en"))
    assert "3 questions · 3 points · cs, uk" in html
    assert "snapshot_hash" in html
    before = html.split("<details>")[0]
    assert "Before" not in before and "Before" in html


def test_later_publication_still_shows_the_diff(logged_in):
    quiz = published_quiz()
    add_question(quiz, OPTION_B, question_id=authoring.editable_questions(quiz)[0]["id"])
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/publish?lang=en"))
    assert "Before" in html and "questions ·" not in html


@pytest.mark.parametrize(("count", "word"), [(1, "otázka"), (2, "otázky"), (5, "otázek")])
def test_first_publication_summary_inflects_in_czech(logged_in, count, word):
    quiz = make_quiz()
    for _ in range(count):
        add_question(quiz)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/publish?lang=cs"))
    assert f"{count} {word} ·" in html


def test_the_new_quiz_form_shows_the_quiz_type_label_once(logged_in):
    html = text(logged_in.get("/admin/quizzes/new"))
    block = html.split('class="quiz-type-choice"')[1].split("</details>")[0]
    assert block.count("<summary>") == 1
    assert "<legend" not in block

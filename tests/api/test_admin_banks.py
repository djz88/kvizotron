import io
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from app.domain import authoring, banks
from app.domain.models import BankQuestion, QuestionBank
from tests.domain.helpers import (
    ADMIN_ID,
    add_bank_question,
    add_question,
    add_row,
    bank_with,
    make_bank,
    make_quiz,
)

pytestmark = pytest.mark.django_db
QUESTION = {"prompt_cs": "Otázka", "option_0_cs": "A", "option_1_cs": "B", "correct_1": "on"}


def text(response):
    return response.content.decode()


def new_url(bank):
    return f"/admin/banks/{bank.id}/questions/new?type=choice"


def test_banks_require_login(client):
    assert client.get("/admin/banks").status_code == 302


def test_nav_links_to_banks(logged_in):
    html = text(logged_in.get("/admin/banks"))
    assert 'href="/admin/banks" aria-current="page"' in html


def test_create_and_rename_a_bank(logged_in):
    assert logged_in.post("/admin/banks", {"name": "Zeměpis"}).status_code == 302
    bank = QuestionBank.objects.get()
    assert bank.name == "Zeměpis"
    assert logged_in.post(f"/admin/banks/{bank.id}", {"name": "Svět"}).status_code == 302
    bank.refresh_from_db()
    assert bank.name == "Svět"


def test_bank_page_lists_questions_tags_and_languages(logged_in):
    bank = bank_with(1, locales=("cs", "uk"), tags=("20. století",))
    html = text(logged_in.get(f"/admin/banks/{bank.id}"))
    assert "Banka 0" in html
    assert "20. století" in html
    assert "cs, uk" in html


def test_bank_editor_has_three_languages_tags_and_no_points(logged_in):
    html = text(logged_in.get(new_url(make_bank())))
    for locale in ("cs", "en", "uk"):
        assert f'name="prompt_{locale}"' in html
        assert f'name="explanation_{locale}"' in html
    assert 'name="tags"' in html
    assert 'name="points"' not in html


def test_saving_a_question_returns_to_the_bank(logged_in):
    bank = make_bank()
    response = logged_in.post(new_url(bank), QUESTION | {"tags": "a, b ,, a"})
    assert response.status_code == 302
    assert response["Location"] == f"/admin/banks/{bank.id}"
    assert BankQuestion.objects.get().tags == ["a", "b"]


def test_question_without_a_complete_language_is_refused_and_keeps_the_form(logged_in):
    bank = make_bank()
    response = logged_in.post(new_url(bank), {"prompt_cs": "Rozepsaná", "tags": "a"})
    assert response.status_code == 200
    assert "Rozepsaná" in text(response)
    assert not BankQuestion.objects.exists()


def test_too_many_tags_are_refused(logged_in):
    bank = make_bank()
    tags = ",".join(f"t{number}" for number in range(11))
    assert logged_in.post(new_url(bank), QUESTION | {"tags": tags}).status_code == 200
    assert not BankQuestion.objects.exists()


def test_too_long_tag_is_refused(logged_in):
    bank = make_bank()
    assert logged_in.post(new_url(bank), QUESTION | {"tags": "x" * 41}).status_code == 200


def test_edit_keeps_tags(logged_in):
    bank = bank_with(1, tags=("a",))
    question = BankQuestion.objects.get()
    url = f"/admin/banks/{bank.id}/questions/{question.pk}/edit"
    assert 'value="a"' in text(logged_in.get(url))
    assert logged_in.post(url, QUESTION | {"tags": "b"}).status_code == 302
    question.refresh_from_db()
    assert question.tags == ["b"]


def test_delete_question(logged_in):
    bank = bank_with(1)
    question = BankQuestion.objects.get()
    response = logged_in.post(f"/admin/banks/{bank.id}/questions/{question.pk}/delete")
    assert response.status_code == 302
    assert not BankQuestion.objects.exists()


def test_delete_bank_in_use_names_the_quiz(logged_in):
    bank = bank_with(1)
    quiz = make_quiz(slug="pouziva-banku")
    add_row(quiz, bank)
    response = logged_in.post(f"/admin/banks/{bank.id}/delete")
    assert response.status_code == 409
    assert "pouziva-banku" in text(response)
    assert QuestionBank.objects.exists()


def test_image_upload_works_on_the_bank_editor(admin_user, settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    browser = Client()  # sends multipart, as a browser does for this form
    browser.force_login(admin_user)
    bank = make_bank()
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 10, 10)).save(buffer, "PNG")
    image = SimpleUploadedFile("a.png", buffer.getvalue(), content_type="image/png")
    form = QUESTION | {"image": image, "image_alt_cs": "Popis"}
    assert browser.post(new_url(bank), form).status_code == 302
    assert BankQuestion.objects.get().question_json["definition"]["image"]["asset"]


def test_multipart_is_allowed_only_on_question_routes(logged_in):
    bank = make_bank()
    body = b'--x\r\nContent-Disposition: form-data; name="name"\r\n\r\nN\r\n--x--\r\n'
    kind = "multipart/form-data; boundary=x"
    refused = logged_in.generic("POST", f"/admin/banks/{bank.id}", body, content_type=kind)
    assert refused.status_code == 415
    allowed = logged_in.generic("POST", new_url(bank), body, content_type=kind)
    assert allowed.status_code != 415


def test_double_save_with_one_form_key_creates_one_question(logged_in):
    bank = make_bank()
    html = text(logged_in.get(new_url(bank)))
    key = re.search(r'name="form_key" value="([^"]+)"', html).group(1)
    form = QUESTION | {"form_key": key}
    assert logged_in.post(new_url(bank), form).status_code == 302
    assert logged_in.post(new_url(bank), form).status_code == 302
    assert BankQuestion.objects.count() == 1


def draw_form(bank, **fields):
    return {"bank": str(bank.id), "tag": "", "count": "2", "points": "3", "position": "0"} | fields


def test_quiz_questions_page_shows_the_row_and_usable_count(logged_in):
    bank = bank_with(3, name="Dějiny")
    quiz = make_quiz()
    add_row(quiz, bank, count=2, points=3)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert "Dějiny" in html
    assert "3 z 3" in html


def test_adding_a_row(logged_in):
    bank = bank_with(3)
    quiz = make_quiz()
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/draws/new", draw_form(bank))
    assert response.status_code == 302
    row = authoring.editable_draws(quiz)[0]
    assert (row["count"], row["points"], row["bank_id"]) == (2, 3, str(bank.id))


@pytest.mark.parametrize(
    "fields", [{"count": "0"}, {"count": "101"}, {"points": "0"}, {"points": "101"}]
)
def test_draw_form_refuses_count_and_points_out_of_range(logged_in, fields):
    bank = bank_with(1)
    quiz = make_quiz()
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/draws/new", draw_form(bank, **fields))
    assert response.status_code == 200
    assert authoring.editable_draws(quiz) == []


def test_editing_and_deleting_a_row(logged_in):
    bank = bank_with(3)
    quiz = make_quiz()
    row = add_row(quiz, bank)
    url = f"/admin/quizzes/{quiz.id}/draws/{row}"
    assert logged_in.post(f"{url}/edit", draw_form(bank, count="3")).status_code == 302
    assert authoring.editable_draws(quiz)[0]["count"] == 3
    assert logged_in.post(f"{url}/delete").status_code == 302
    assert authoring.editable_draws(quiz) == []


def test_row_appears_at_its_position(logged_in):
    bank = bank_with(1, name="Řádek banky")
    quiz = make_quiz()
    add_question(quiz, prompt="První")
    add_question(quiz, prompt="Druhá")
    add_row(quiz, bank, position=1)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert html.index("První") < html.index("Řádek banky") < html.index("Druhá")


def test_archived_quiz_cannot_get_a_row(logged_in):
    bank = bank_with(1)
    quiz = make_quiz()
    add_question(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/draws/new", draw_form(bank))
    assert response.status_code == 409
    assert banks.tags_of(bank) == []


def test_publication_page_lists_a_bank_change(logged_in):
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    add_bank_question(bank, prompt="Nová otázka")
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/publish"))
    assert "Nová otázka" in html


def test_revision_list_counts_drawn_questions(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    add_row(quiz, bank_with(5), count=3, points=2)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/revisions"))
    assert re.search(r'data-label="Otázky">4</td>', html)

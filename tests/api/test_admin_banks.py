import io
import re
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from app.domain import authoring, bank_folders, banks
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
    assert logged_in.post(f"/admin/banks/{bank.id}/name", {"name": "Svět"}).status_code == 302
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


def test_adding_a_row_with_a_folder(logged_in):
    """AC-154: a draw row can name a folder of its bank."""
    bank = bank_with(2)
    folder = bank_folders.create(bank, None, "EU", admin_id=ADMIN_ID)
    quiz = make_quiz()
    form = draw_form(bank, folder=str(folder.pk))
    assert logged_in.post(f"/admin/quizzes/{quiz.id}/draws/new", form).status_code == 302
    row = authoring.editable_draws(quiz)[0]
    assert (row["folder_id"], row["folder_path"]) == (str(folder.pk), "EU")


def test_a_folder_of_another_bank_is_refused_by_the_draw_form(logged_in):
    bank, other = bank_with(1, name="A"), make_bank("B")
    foreign = bank_folders.create(other, None, "x", admin_id=ADMIN_ID)
    quiz = make_quiz()
    form = draw_form(bank, folder=str(foreign.pk))
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/draws/new", form)
    assert response.status_code == 200
    assert authoring.editable_draws(quiz) == []


def test_editing_a_row_offers_and_keeps_its_folder(logged_in):
    bank = bank_with(1)
    folder = bank_folders.create(bank, None, "EU", admin_id=ADMIN_ID)
    quiz = make_quiz()
    row = add_row(quiz, bank, folder_id=str(folder.pk))
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/draws/{row}/edit"))
    assert re.search(rf'<option value="{folder.pk}"[^>]*selected[^>]*>[^<]*EU', html)
    assert '<option value="" ' in html or '<option value="">' in html


def test_quiz_questions_page_shows_the_folder_of_a_row(logged_in):
    bank = bank_with(1)
    folder = bank_folders.create(
        bank, bank_folders.create(bank, None, "EU", admin_id=ADMIN_ID), "obchod", admin_id=ADMIN_ID
    )
    quiz = make_quiz()
    add_row(quiz, bank, folder_id=str(folder.pk))
    assert "EU/obchod" in text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))


def plain(response):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text(response)))


def folder_url(bank, folder=None, action=""):
    base = f"/admin/banks/{bank.id}/folders"
    return f"{base}/{folder.pk}/{action}" if folder else f"{base}/new"


def put(question_id, folder):
    BankQuestion.objects.filter(pk=question_id).update(folder=folder)


def tree_bank():
    bank = make_bank("Evropa")
    eu = bank_folders.create(bank, None, "EU", admin_id=ADMIN_ID)
    trade = bank_folders.create(bank, eu, "obchod", admin_id=ADMIN_ID)
    geo = bank_folders.create(bank, eu, "geopolitika", admin_id=ADMIN_ID)
    ids = {}
    for name, folder in (("eu1", eu), ("t1", trade), ("t2", trade), ("g1", geo), ("loose", None)):
        ids[name] = add_bank_question(bank, prompt=name)
        put(ids[name], folder)
    return bank, {"eu": eu, "trade": trade, "geo": geo}, ids


def test_bank_page_shows_the_tree_counts(logged_in):
    """AC-155: the bank page lists folders with their question and subfolder counts."""
    bank, folders, _ids = tree_bank()
    page = plain(logged_in.get(f"/admin/banks/{bank.id}"))
    assert re.search(r"EU\D*4\D*2", page)
    inner = plain(logged_in.get(f"/admin/banks/{bank.id}?folder={folders['eu'].pk}"))
    assert re.search(r"obchod\D*2\D*0", inner)
    assert re.search(r"geopolitika\D*1\D*0", inner)


def test_a_folder_page_lists_only_its_own_questions(logged_in):
    bank, folders, _ids = tree_bank()
    html = text(logged_in.get(f"/admin/banks/{bank.id}?folder={folders['trade'].pk}"))
    assert "t1 cs" in html and "t2 cs" in html
    assert "eu1 cs" not in html and "g1 cs" not in html and "loose cs" not in html


def test_the_top_level_lists_unfiled_questions(logged_in):
    bank, _folders, _ids = tree_bank()
    html = text(logged_in.get(f"/admin/banks/{bank.id}"))
    assert "loose cs" in html and "t1 cs" not in html


def test_an_unknown_folder_is_a_404(logged_in):
    bank, _folders, _ids = tree_bank()
    assert logged_in.get(f"/admin/banks/{bank.id}?folder=not-an-id").status_code == 404
    other = bank_folders.create(make_bank("B"), None, "x", admin_id=ADMIN_ID)
    assert logged_in.get(f"/admin/banks/{bank.id}?folder={other.pk}").status_code == 404


def test_search_shows_hits_with_their_path_and_escapes(logged_in):
    """AC-155: search finds questions in the whole bank and shows where each lies."""
    bank, _folders, _ids = tree_bank()
    html = text(logged_in.get(f"/admin/banks/{bank.id}?q=OBCHOD"))
    assert "EU/obchod" in html and "t1 cs" in html and "t2 cs" in html
    assert "g1 cs" not in html
    bank_folders.create(bank, None, "<img src=x onerror=alert(1)>", admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/banks/{bank.id}?q=%3Cimg+src%3Dx"))
    assert "<img src=x" not in html and "&lt;img src=x" in html
    assert "<img src=x" not in text(logged_in.get(f"/admin/banks/{bank.id}"))


def test_create_rename_move_and_delete_a_folder(logged_in):
    bank = make_bank()
    assert logged_in.post(folder_url(bank), {"name": "EU", "parent": ""}).status_code == 302
    eu = bank_folders.ensure_path(bank, "EU", admin_id=ADMIN_ID)
    logged_in.post(folder_url(bank), {"name": "obchod", "parent": str(eu.pk)})
    trade = bank_folders.ensure_path(bank, "EU/obchod", admin_id=ADMIN_ID)
    assert logged_in.post(folder_url(bank, trade, "rename"), {"name": "trh"}).status_code == 302
    trade.refresh_from_db()
    assert trade.name == "trh"
    assert logged_in.post(folder_url(bank, trade, "move"), {"parent": ""}).status_code == 302
    trade.refresh_from_db()
    assert trade.parent_id is None
    assert logged_in.post(folder_url(bank, trade, "delete")).status_code == 302
    assert not bank.folders.filter(name="trh").exists()


def test_deleting_a_folder_with_content_shows_the_message(logged_in):
    bank, folders, _ids = tree_bank()
    response = logged_in.post(folder_url(bank, folders["trade"], "delete"), {})
    assert response.status_code == 400
    assert bank.folders.filter(pk=folders["trade"].pk).exists()
    assert "obchod" in text(response)


def test_moving_a_folder_into_its_own_child_shows_an_error(logged_in):
    bank, folders, _ids = tree_bank()
    url = folder_url(bank, folders["eu"], "move")
    response = logged_in.post(url, {"parent": str(folders["trade"].pk)})
    assert response.status_code == 400
    folders["eu"].refresh_from_db()
    assert folders["eu"].parent_id is None


def test_a_bad_folder_name_shows_an_error(logged_in):
    bank = make_bank()
    assert logged_in.post(folder_url(bank), {"name": "a/b", "parent": ""}).status_code == 400
    assert not bank.folders.exists()


def test_bulk_move_moves_the_chosen_questions(logged_in):
    """AC-156: chosen questions move to a folder or are unfiled in one action."""
    bank, folders, ids = tree_bank()
    url = f"/admin/banks/{bank.id}/questions/move"
    data = {"question": [ids["loose"], ids["eu1"]], "folder": str(folders["geo"].pk)}
    assert logged_in.post(url, data).status_code == 302
    assert BankQuestion.objects.get(pk=ids["loose"]).folder_id == folders["geo"].pk
    assert logged_in.post(url, {"question": [ids["loose"]], "folder": ""}).status_code == 302
    assert BankQuestion.objects.get(pk=ids["loose"]).folder_id is None


def test_bulk_move_with_a_foreign_question_changes_nothing(logged_in):
    bank, folders, ids = tree_bank()
    foreign = add_bank_question(make_bank("B"))
    url = f"/admin/banks/{bank.id}/questions/move"
    data = {"question": [ids["loose"], foreign], "folder": str(folders["geo"].pk)}
    assert logged_in.post(url, data).status_code == 400
    assert BankQuestion.objects.get(pk=ids["loose"]).folder_id is None
    assert logged_in.post(url, {"folder": str(folders["geo"].pk)}).status_code == 400


def test_the_folder_views_need_an_admin(client):
    bank, folders, _ids = tree_bank()
    for url in (
        folder_url(bank),
        folder_url(bank, folders["eu"], "rename"),
        folder_url(bank, folders["eu"], "move"),
        folder_url(bank, folders["eu"], "delete"),
        f"/admin/banks/{bank.id}/questions/move",
    ):
        response = client.post(url, {})
        assert response.status_code == 302 and "login" in response["Location"]
    assert bank.folders.count() == 3


def test_a_question_can_be_saved_into_a_folder(logged_in):
    bank = make_bank()
    folder = bank_folders.create(bank, None, "EU", admin_id=ADMIN_ID)
    assert logged_in.post(new_url(bank), QUESTION | {"folder": str(folder.pk)}).status_code == 302
    assert BankQuestion.objects.get().folder_id == folder.pk


def test_a_new_question_opened_from_a_folder_preselects_it(logged_in):
    bank = make_bank()
    folder = bank_folders.create(bank, None, "EU", admin_id=ADMIN_ID)
    html = text(logged_in.get(f"{new_url(bank)}&folder={folder.pk}"))
    assert re.search(rf'<option value="{folder.pk}"[^>]*selected', html)


def test_editing_shows_the_folder_of_the_question_and_can_unfile_it(logged_in):
    bank = bank_with(1)
    folder = bank_folders.create(bank, None, "EU", admin_id=ADMIN_ID)
    question = BankQuestion.objects.get()
    put(question.pk, folder)
    url = f"/admin/banks/{bank.id}/questions/{question.pk}/edit"
    assert re.search(rf'<option value="{folder.pk}"[^>]*selected', text(logged_in.get(url)))
    assert logged_in.post(url, QUESTION | {"folder": ""}).status_code == 302
    question.refresh_from_db()
    assert question.folder_id is None


def test_a_folder_of_another_bank_is_refused_in_the_editor(logged_in):
    bank = make_bank()
    foreign = bank_folders.create(make_bank("B"), None, "x", admin_id=ADMIN_ID)
    response = logged_in.post(new_url(bank), QUESTION | {"folder": str(foreign.pk)})
    assert response.status_code == 200
    assert not BankQuestion.objects.exists()


def test_a_renamed_folder_shows_its_new_path_on_the_draw_row(logged_in):
    """AC-154: the row refers to the folder by id, so a rename shows at once."""
    bank = bank_with(1)
    folder = bank_folders.create(bank, None, "obchod", admin_id=ADMIN_ID)
    quiz = make_quiz()
    add_row(quiz, bank, folder_id=str(folder.pk))
    bank_folders.rename(folder, "komerce", admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert "komerce" in html and "obchod" not in html


def test_editing_a_row_whose_folder_is_gone_warns_before_it_widens_the_draw(logged_in):
    bank = bank_with(1)
    folder = bank_folders.create(bank, None, "zmizela", admin_id=ADMIN_ID)
    quiz = make_quiz()
    row = add_row(quiz, bank, folder_id=str(folder.pk))
    bank_folders.delete(folder, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/draws/{row}/edit"))
    assert 'role="alert"' in html and "zmizela" in html
    ok = bank_with(1, name="Jiná")
    folder_ok = bank_folders.create(ok, None, "zije", admin_id=ADMIN_ID)
    row_ok = add_row(quiz, ok, folder_id=str(folder_ok.pk))
    assert 'role="alert"' not in text(
        logged_in.get(f"/admin/quizzes/{quiz.id}/draws/{row_ok}/edit")
    )


def test_the_top_of_a_bank_shows_how_many_questions_are_unfiled(logged_in):
    bank, _folders, _ids = tree_bank()
    html = plain(logged_in.get(f"/admin/banks/{bank.id}"))
    assert re.search(r"Nezařazené \(1\)", html)


def test_the_folder_menu_moves_straight_from_a_select_and_a_phone_gets_links(logged_in):
    """AC-155: the menu of a folder has a select with every destination; a phone has links."""
    bank, folders, _ids = tree_bank()
    other = make_bank("XXX")
    html = text(logged_in.get(f"/admin/banks/{bank.id}?folder={folders['eu'].pk}"))
    move_url = f"/admin/banks/{bank.id}/folders/{folders['trade'].pk}/move"
    forms = re.findall(rf'<form[^>]*action="{move_url}"[^>]*>(.*?)</form>', html, re.S)
    inline = [f for f in forms if "<select" in f]
    plain_top = [f for f in forms if "<select" not in f]
    assert len(inline) == 1 and len(plain_top) == 1
    values = re.findall(r'<option value="([^"]*)"', inline[0])
    assert values[0] == "" and f"bank:{other.pk}" in values and "newbank" in values
    assert str(folders["geo"].pk) in values and str(folders["trade"].pk) not in values
    assert 'name="parent" value=""' in plain_top[0]
    assert f'href="{move_url}"' in html  # the phone link to the page with the choice
    for kind in ("move-inline", "move-links"):
        assert f'class="{kind}"' in html


def test_a_folder_at_the_top_has_no_one_click_move_to_the_top(logged_in):
    bank, folders, _ids = tree_bank()
    top = text(logged_in.get(f"/admin/banks/{bank.id}"))
    eu_move = f"/admin/banks/{bank.id}/folders/{folders['eu'].pk}/move"
    forms = re.findall(rf'<form[^>]*action="{eu_move}"[^>]*>(.*?)</form>', top, re.S)
    assert len(forms) == 1 and "<select" in forms[0]


def test_the_move_page_offers_the_top_and_every_valid_destination(logged_in):
    bank, folders, _ids = tree_bank()
    url = f"/admin/banks/{bank.id}/folders/{folders['eu'].pk}/move"
    html = text(logged_in.get(url))
    assert logged_in.get(url).status_code == 200
    options = re.findall(r'<option value="([^"]*)"', html)
    assert options[0] == ""
    assert str(folders["eu"].pk) not in options  # not into itself
    assert str(folders["trade"].pk) not in options  # nor into its own subfolder
    other = f"/admin/banks/{bank.id}/folders/{folders['trade'].pk}/move"
    assert str(folders["geo"].pk) in re.findall(
        r'<option value="([^"]*)"', text(logged_in.get(other))
    )


def test_moving_to_the_top_lands_on_the_moved_folder(logged_in):
    bank, folders, _ids = tree_bank()
    url = f"/admin/banks/{bank.id}/folders/{folders['trade'].pk}/move"
    response = logged_in.post(url, {"parent": ""})
    assert response.status_code == 302
    assert response["Location"].endswith(f"?folder={folders['trade'].pk}")
    folders["trade"].refresh_from_db()
    assert folders["trade"].parent_id is None


def test_a_refused_move_shows_the_move_page_with_the_message(logged_in):
    bank, folders, _ids = tree_bank()
    url = f"/admin/banks/{bank.id}/folders/{folders['eu'].pk}/move"
    response = logged_in.post(url, {"parent": str(folders["trade"].pk)})
    assert response.status_code == 400
    html = text(response)
    assert 'role="alert"' in html and "<option" in html
    folders["eu"].refresh_from_db()
    assert folders["eu"].parent_id is None


def test_the_move_page_of_a_folder_of_another_bank_is_a_404(logged_in):
    bank, _folders, _ids = tree_bank()
    foreign = bank_folders.create(make_bank("B"), None, "x", admin_id=ADMIN_ID)
    assert logged_in.get(f"/admin/banks/{bank.id}/folders/{foreign.pk}/move").status_code == 404


def move_url(bank, folder):
    return f"/admin/banks/{bank.id}/folders/{folder.pk}/move"


def test_the_move_page_offers_other_banks_and_a_new_bank(logged_in):
    """AC-159: the move page offers other banks (top and folders) and a new bank."""
    bank, folders, _ids = tree_bank()
    other = make_bank("XXX")
    inside = bank_folders.create(other, None, "Evropa", admin_id=ADMIN_ID)
    html = text(logged_in.get(move_url(bank, folders["eu"])))
    values = re.findall(r'<option value="([^"]*)"', html)
    assert f"bank:{other.pk}" in values and str(inside.pk) in values and "newbank" in values
    assert values[0] == ""
    assert "XXX / Evropa" in html


def test_a_folder_becomes_a_new_bank_through_the_move_page(logged_in):
    bank, folders, ids = tree_bank()
    response = logged_in.post(move_url(bank, folders["eu"]), {"parent": "newbank"})
    assert response.status_code == 302
    new = QuestionBank.objects.get(name="EU")
    assert response["Location"] == f"/admin/banks/{new.pk}"
    assert BankQuestion.objects.get(pk=ids["t1"]).bank_id == new.pk
    assert not bank.folders.exists()


def test_a_folder_moves_to_another_bank_through_the_move_page(logged_in):
    bank, folders, ids = tree_bank()
    other = make_bank("XXX")
    response = logged_in.post(move_url(bank, folders["trade"]), {"parent": f"bank:{other.pk}"})
    assert response.status_code == 302
    assert response["Location"].endswith(f"/admin/banks/{other.pk}?folder={folders['trade'].pk}")
    folders["trade"].refresh_from_db()
    assert (folders["trade"].bank_id, folders["trade"].parent_id) == (other.pk, None)
    target = bank_folders.create(other, None, "Evropa", admin_id=ADMIN_ID)
    logged_in.post(move_url(other, folders["trade"]), {"parent": str(target.pk)})
    folders["trade"].refresh_from_db()
    assert folders["trade"].parent_id == target.pk
    assert BankQuestion.objects.get(pk=ids["t1"]).bank_id == other.pk


def test_a_folder_a_draw_row_names_cannot_leave_and_the_page_says_so(logged_in):
    bank, folders, _ids = tree_bank()
    quiz = make_quiz(slug="pouziva-slozku")
    add_row(quiz, bank, folder_id=str(folders["trade"].pk))
    response = logged_in.post(move_url(bank, folders["eu"]), {"parent": "newbank"})
    assert response.status_code == 400
    assert "pouziva-slozku" in text(response)
    assert not QuestionBank.objects.filter(name="EU").exists()


def test_an_unknown_destination_is_a_404(logged_in):
    bank, folders, _ids = tree_bank()
    for value in ("bank:not-an-id", "not-an-id", f"bank:{uuid.uuid4()}", str(uuid.uuid4())):
        assert logged_in.post(move_url(bank, folders["eu"]), {"parent": value}).status_code == 404


def test_the_folder_trail_starts_with_a_section_not_with_the_name_of_the_bank(logged_in):
    """AC-155: the top of the trail says "Folders", so the bank is not taken for a folder."""
    bank, folders, _ids = tree_bank()
    for url in (f"/admin/banks/{bank.id}", f"/admin/banks/{bank.id}?folder={folders['eu'].pk}"):
        html = text(logged_in.get(url))
        crumbs = re.search(r'<nav class="folder-crumbs".*?</nav>', html, re.S).group(0)
        assert "Složky" in crumbs
        assert bank.name not in crumbs
        assert f'<h1 class="inline-name-text">{bank.name}</h1>' in html


def test_draw_form_offers_the_four_difficulties(logged_in):
    quiz = make_quiz()
    make_bank()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/draws/new"))
    assert 'name="difficulty"' in html
    for value in ("", "easy", "normal", "hard"):
        assert f'<option value="{value}"' in html


def test_adding_a_row_with_a_difficulty(logged_in):
    """AC-163: the draw form saves the difficulty; without it the row is a random mix."""
    bank = bank_with(3)
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/draws/new"
    assert logged_in.post(url, draw_form(bank, difficulty="hard")).status_code == 302
    assert logged_in.post(url, draw_form(bank)).status_code == 302
    assert [row["difficulty"] for row in authoring.editable_draws(quiz)] == ["hard", ""]


def test_an_unknown_difficulty_is_refused(logged_in):
    bank = bank_with(1)
    quiz = make_quiz()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/draws/new", draw_form(bank, difficulty="impossible")
    )
    assert response.status_code == 200
    assert authoring.editable_draws(quiz) == []


def test_editing_a_row_written_before_levels_shows_the_random_mix(logged_in):
    bank = bank_with(3)
    quiz = make_quiz()
    row = add_row(quiz, bank)
    stored = authoring.get_draft(quiz)
    del stored.snapshot_json["draws"][0]["difficulty"]
    stored.save()
    url = f"/admin/quizzes/{quiz.id}/draws/{row}"
    html = text(logged_in.get(f"{url}/edit"))
    assert re.search(r'<option value="" selected', html)
    assert logged_in.post(f"{url}/edit", draw_form(bank)).status_code == 302
    assert authoring.editable_draws(quiz)[0]["difficulty"] == ""


def row_details(html):
    """The small line under the first draw row of the quiz editor."""
    return re.search(r'<li class="draw-row">.*?<small>(.*?)</small>', html, re.S).group(1)


def test_the_row_shows_its_level_in_the_quiz_editor(logged_in):
    bank = bank_with(3, name="Dějiny")
    quiz = make_quiz()
    add_row(quiz, bank, difficulty="easy")
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert banks.level_label("easy") in html
    plain = make_quiz("jiny")
    add_row(plain, bank)
    with_level = row_details(html)
    html = text(logged_in.get(f"/admin/quizzes/{plain.id}/edit"))
    assert with_level.count("·") == row_details(html).count("·") + 1


def test_two_level_tags_are_refused_by_the_bank_question_form(logged_in):
    """AC-164: the bank question form refuses two level tags and saves nothing."""
    bank = make_bank()
    response = logged_in.post(new_url(bank), QUESTION | {"tags": "easy, hard"})
    assert response.status_code == 200
    assert "only one of the tags" in text(response) or "jen jeden ze štítků" in text(response)
    assert not BankQuestion.objects.exists()
    assert logged_in.post(new_url(bank), QUESTION | {"tags": "easy, EU"}).status_code == 302
    assert BankQuestion.objects.get().tags == ["easy", "EU"]

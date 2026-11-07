"""An image from an address: what the editor stores and what a participant gets (AC-38 to AC-40).

The media provider is real; only the network below it is replaced.
"""

import io
import re
from unittest import mock

import pytest
from django.test import Client
from PIL import Image

from app.contracts import ALLOW_INTERNAL_IMAGE_ADDRESSES, EXTERNAL_IMAGE_MODE
from app.domain import authoring, questions, settings
from app.domain.models import QuizRevision
from app.providers.media_local import remote
from app.providers.media_local.provider import LocalMediaStorage
from tests.api.test_play import Play
from tests.domain.helpers import ADMIN_ID, OPTION_A, definition, make_bank, make_quiz

pytestmark = pytest.mark.django_db
URL = "https://obrazky.example/a.png"
OTHER = "https://obrazky.example/b.png"
MODE = f"setting_{EXTERNAL_IMAGE_MODE}"
QUESTION = {"prompt_cs": "Otázka", "option_0_cs": "A", "option_1_cs": "B", "correct_1": "on"}
WITH_ADDRESS = QUESTION | {"image_source": URL, "image_alt_cs": "Popis"}
HTMX = {"HX-Request": "true"}


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)


@pytest.fixture
def uploader(admin_user):
    """A browser sends this form as multipart; FormClient does not."""
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def fetch(monkeypatch):
    fake = mock.Mock(side_effect=lambda *a, **k: png())
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


@pytest.fixture
def down(monkeypatch):
    fake = mock.Mock(side_effect=remote.RemoteRefused("down"))
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


def new_url(quiz):
    return f"/admin/quizzes/{quiz.id}/questions/new?type=choice"


def only(quiz):
    return authoring.editable_questions(quiz)[0]


def edit_url(quiz):
    return f"/admin/quizzes/{quiz.id}/questions/{only(quiz)['id']}/edit"


def resubmit(quiz, **fields):
    """What the browser sends back for the stored image, as the editor drew it."""
    image = only(quiz)["definition"]["image"]
    form = QUESTION | {"image_source": image.get("source", ""), "image_alt_cs": "Popis"}
    if image.get("asset"):
        form |= {"image_asset": image["asset"], "image_kept_source": image.get("source", "")}
    return form | fields


# The editor


def test_an_address_stores_a_copy_and_keeps_the_source(logged_in, fetch):
    quiz = make_quiz()
    assert logged_in.post(new_url(quiz), WITH_ADDRESS).status_code == 302
    image = only(quiz)["definition"]["image"]
    assert image["source"] == URL
    assert LocalMediaStorage().exists(image["asset"])
    assert image["alt"] == {"cs": "Popis"}


def test_the_fetch_uses_the_internal_switch(logged_in, fetch):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), WITH_ADDRESS)
    assert fetch.call_args.kwargs["allow_internal"] is False
    settings.set_global(ALLOW_INTERNAL_IMAGE_ADDRESSES, "on", admin_id=ADMIN_ID)
    logged_in.post(new_url(make_quiz("druhy")), WITH_ADDRESS)
    assert fetch.call_args.kwargs["allow_internal"] is True


def test_an_unchanged_address_fetches_nothing(logged_in, fetch):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), WITH_ADDRESS)
    asset = only(quiz)["definition"]["image"]["asset"]
    fetch.reset_mock()
    assert logged_in.post(edit_url(quiz), resubmit(quiz)).status_code == 302
    fetch.assert_not_called()
    assert only(quiz)["definition"]["image"]["asset"] == asset


def test_a_changed_address_fetches_again(logged_in, fetch):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), WITH_ADDRESS)
    asset = only(quiz)["definition"]["image"]["asset"]
    fetch.reset_mock()
    logged_in.post(edit_url(quiz), resubmit(quiz, image_source=OTHER))
    fetch.assert_called_once()
    image = only(quiz)["definition"]["image"]
    assert image["source"] == OTHER
    assert image["asset"] != asset


def test_an_address_without_a_copy_is_tried_again_on_each_save(logged_in, down):
    quiz = make_quiz()
    settings.set_override(EXTERNAL_IMAGE_MODE, quiz, "external", admin_id=ADMIN_ID)
    logged_in.post(new_url(quiz), WITH_ADDRESS)
    assert only(quiz)["definition"]["image"]["asset"] is None
    remote.fetch.side_effect = lambda *a, **k: png()
    logged_in.post(edit_url(quiz), resubmit(quiz))
    assert only(quiz)["definition"]["image"]["asset"]


def test_a_file_beats_an_address(uploader, fetch):
    quiz = make_quiz()
    upload = io.BytesIO(png())
    upload.name = "a.png"
    assert uploader.post(new_url(quiz), WITH_ADDRESS | {"image": upload}).status_code == 302
    fetch.assert_not_called()
    image = only(quiz)["definition"]["image"]
    assert image["asset"]
    assert "source" not in image


@pytest.mark.parametrize("mode", ["copy", "external"])
@pytest.mark.parametrize("address", ["http://a.example/x.png", "nonsense", "https://u:p@a.cz/x"])
def test_a_bad_address_is_refused_in_both_modes(logged_in, fetch, mode, address):
    quiz = make_quiz()
    form = WITH_ADDRESS | {"image_source": address, MODE: mode}
    response = logged_in.post(new_url(quiz), form)
    assert response.status_code == 200
    assert authoring.editable_questions(quiz) == []
    fetch.assert_not_called()


def test_a_forged_unchanged_address_is_still_checked(logged_in, fetch):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), WITH_ADDRESS)
    bad = "javascript:alert(1)"
    form = resubmit(quiz, image_source=bad, image_kept_source=bad)
    assert logged_in.post(edit_url(quiz), form).status_code == 200
    assert only(quiz)["definition"]["image"]["source"] == URL


def test_failure_in_copy_mode_returns_the_form_with_its_data(uploader, monkeypatch):
    """Review Focus 3: another image's stored file stays too."""
    quiz = make_quiz()
    upload = io.BytesIO(png())
    upload.name = "a.png"
    monkeypatch.setattr(remote, "fetch", mock.Mock(side_effect=remote.RemoteRefused("down")))
    form = WITH_ADDRESS | {"option_0_image": upload, "option_0_image_alt_cs": "Soubor"}
    response = uploader.post(new_url(quiz), form)
    html = response.content.decode()
    assert response.status_code == 200
    assert authoring.editable_questions(quiz) == []
    assert f'value="{URL}"' in html
    assert 'value="Popis"' in html
    assert re.search(r'name="option_0_image_asset" value="[0-9a-f-]{36}"', html)
    assert 'role="alert"' in html


def test_failure_in_external_mode_saves_without_a_copy_and_marks_it(logged_in, down):
    quiz = make_quiz()
    settings.set_override(EXTERNAL_IMAGE_MODE, quiz, "external", admin_id=ADMIN_ID)
    assert logged_in.post(new_url(quiz), WITH_ADDRESS).status_code == 302
    image = only(quiz)["definition"]["image"]
    assert image["asset"] is None
    assert image["source"] == URL
    page = logged_in.get(f"/admin/quizzes/{quiz.id}/edit?lang=en").content.decode()
    assert "No copy of an image" in page


def test_the_mode_submitted_on_the_form_decides_at_save(logged_in, down):
    quiz = make_quiz()
    assert logged_in.post(new_url(quiz), WITH_ADDRESS | {MODE: "external"}).status_code == 302
    assert only(quiz)["settings"][EXTERNAL_IMAGE_MODE] == "external"


def test_a_question_set_to_copy_is_refused_in_an_external_quiz(logged_in, down):
    quiz = make_quiz()
    settings.set_override(EXTERNAL_IMAGE_MODE, quiz, "external", admin_id=ADMIN_ID)
    assert logged_in.post(new_url(quiz), WITH_ADDRESS | {MODE: "copy"}).status_code == 200


def test_a_bank_question_follows_global_when_it_fails(logged_in, down):
    bank = make_bank()
    url = f"/admin/banks/{bank.id}/questions/new?type=choice"
    assert logged_in.post(url, WITH_ADDRESS).status_code == 200
    assert not bank.questions.exists()
    assert logged_in.post(url, WITH_ADDRESS | {MODE: "external"}).status_code == 302
    image = bank.questions.get().question_json["definition"]["image"]
    assert image["asset"] is None
    assert image["source"] == URL


def test_a_bank_question_stores_a_copy(logged_in, fetch):
    bank = make_bank()
    logged_in.post(f"/admin/banks/{bank.id}/questions/new?type=choice", WITH_ADDRESS)
    assert bank.questions.get().question_json["definition"]["image"]["asset"]


def test_remove_ticked_with_an_address_fetches_nothing(logged_in, fetch):
    """Review Focus 5."""
    quiz = make_quiz()
    logged_in.post(new_url(quiz), WITH_ADDRESS)
    fetch.reset_mock()
    form = resubmit(quiz, image_source=OTHER, image_remove="on")
    assert logged_in.post(edit_url(quiz), form).status_code == 302
    fetch.assert_not_called()
    assert "image" not in only(quiz)["definition"]


def test_clearing_the_address_keeps_the_copy_as_an_ordinary_image(logged_in, fetch):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), WITH_ADDRESS)
    logged_in.post(edit_url(quiz), resubmit(quiz, image_source=""))
    image = only(quiz)["definition"]["image"]
    assert image["asset"]
    assert "source" not in image


def test_the_editor_shows_the_address_and_previews_the_copy(logged_in, fetch):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), WITH_ADDRESS)
    asset = only(quiz)["definition"]["image"]["asset"]
    html = logged_in.get(edit_url(quiz)).content.decode()
    assert f'name="image_source" type="url" value="{URL}"' in html
    assert f'src="/media/{asset}"' in html


def test_the_editor_previews_the_address_without_a_copy(logged_in, down):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), WITH_ADDRESS | {MODE: "external"})
    html = logged_in.get(edit_url(quiz)).content.decode()
    assert f'src="{URL}"' in html
    assert 'name="image_kept_source"' not in html


# What a participant gets


def run_with(image, **setting_values):
    quiz = make_quiz()
    config = definition(("cs",)) | {"image": image}
    config["options"][0]["image"] = image
    authoring.save_question(quiz, None, "choice", config, setting_values=setting_values or None)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def copy_image():
    return {"asset": LocalMediaStorage().store_image(png()), "source": URL, "alt": {"cs": "Popis"}}


def page_of(client, run):
    return client.post(f"/r/{run.id}/start", {"lang": "cs"}, headers=HTMX).content.decode()


def test_a_copy_shows_media_and_no_source_address(client):
    image = copy_image()
    html = page_of(client, run_with(image))
    assert f'src="/media/{image["asset"]}"' in html
    assert URL not in html


def test_external_mode_shows_the_address_with_no_referrer(client):
    run = run_with(copy_image())
    settings.set_override(EXTERNAL_IMAGE_MODE, run.quiz, "external", admin_id=ADMIN_ID)
    html = page_of(client, run)
    assert f'src="{URL}"' in html
    assert "/media/" not in html
    assert re.search(r'<img[^>]*referrerpolicy="no-referrer"', html)


def test_an_image_without_a_copy_shows_the_address_in_any_mode(client):
    """Publication needs `external`; the quiz can go back to copies afterwards."""
    quiz = make_quiz()
    settings.set_override(EXTERNAL_IMAGE_MODE, quiz, "external", admin_id=ADMIN_ID)
    image = {"asset": None, "source": URL, "alt": {"cs": "Popis"}}
    authoring.save_question(quiz, None, "choice", definition(("cs",)) | {"image": image})
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    settings.set_override(EXTERNAL_IMAGE_MODE, quiz, "copy", admin_id=ADMIN_ID)
    assert f'src="{URL}"' in page_of(client, run)


def test_question_beats_quiz_beats_global_for_the_image(client):
    image = copy_image()
    settings.set_global(EXTERNAL_IMAGE_MODE, "copy", admin_id=ADMIN_ID)
    run = run_with(image, **{EXTERNAL_IMAGE_MODE: "copy"})
    settings.set_override(EXTERNAL_IMAGE_MODE, run.quiz, "external", admin_id=ADMIN_ID)
    html = page_of(client, run)
    assert f'src="/media/{image["asset"]}"' in html
    assert URL not in html


def test_removing_the_question_value_follows_the_quiz(client):
    run = run_with(copy_image())
    settings.set_override(EXTERNAL_IMAGE_MODE, run.quiz, "external", admin_id=ADMIN_ID)
    assert f'src="{URL}"' in page_of(client, run)


def test_changing_the_quiz_mode_creates_no_draft():
    run = run_with(copy_image())
    settings.set_override(EXTERNAL_IMAGE_MODE, run.quiz, "external", admin_id=ADMIN_ID)
    assert not QuizRevision.objects.filter(quiz=run.quiz, status=QuizRevision.Status.DRAFT).exists()


def test_a_solution_follows_the_same_mode(client):
    run = run_with(copy_image())
    settings.set_override(settings.REVEAL_MOMENT, run.quiz, "at_end", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_LEVEL, run.quiz, "answers", admin_id=ADMIN_ID)
    settings.set_override(EXTERNAL_IMAGE_MODE, run.quiz, "external", admin_id=ADMIN_ID)
    html = Play(client, run, "cs").submit(OPTION_A).content.decode()
    assert f'src="{URL}"' in html


def test_a_solution_in_copy_mode_hides_the_address(client):
    run = run_with(copy_image())
    settings.set_override(settings.REVEAL_MOMENT, run.quiz, "at_end", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_LEVEL, run.quiz, "answers", admin_id=ADMIN_ID)
    html = Play(client, run, "cs").submit(OPTION_A).content.decode()
    assert "/media/" in html
    assert URL not in html


def test_an_image_from_before_b4_still_shows(client):
    asset = LocalMediaStorage().store_image(png())
    html = page_of(client, run_with({"asset": asset, "alt": {"cs": "Popis"}}))
    assert f'src="/media/{asset}"' in html


def test_images_of_finds_every_image():
    config = definition(("cs",)) | {"image": {"asset": "a", "alt": {}}}
    config["options"][1]["image"] = {"asset": None, "source": URL, "alt": {}}
    assert len(questions.images_of(config)) == 2


def test_images_are_allowed_from_https_only(client):
    policy = client.get("/")["Content-Security-Policy"]
    assert re.search(r"img-src [^;]*https:", policy)
    assert "http:" not in policy


def test_the_privacy_page_mentions_other_servers(client):
    html = client.get("/privacy?lang=en").content.decode()
    assert "IP address" in html
    assert "Pages load nothing from other services." not in html


def test_the_publish_page_names_the_question_with_no_copy(logged_in):
    quiz = make_quiz()
    image = {"asset": None, "source": URL, "alt": {"cs": "Popis"}}
    authoring.save_question(quiz, None, "choice", definition(("cs",)) | {"image": image})
    html = logged_in.get(f"/admin/quizzes/{quiz.id}/publish?lang=en").content.decode()
    assert "Question 1" in html
    assert "no copy" in html.lower()
    assert 'name="decision"' not in html or "disabled" in html


def test_a_later_mode_change_keeps_the_image_playing(client):
    image = {"asset": None, "source": URL, "alt": {"cs": "Popis"}}
    run = run_with(image, **{EXTERNAL_IMAGE_MODE: "external"})
    settings.set_global(EXTERNAL_IMAGE_MODE, "copy", admin_id=ADMIN_ID)
    assert f'src="{URL}"' in page_of(client, run)

import pytest

from app.contracts import EXTERNAL_IMAGE_MODE
from app.domain import authoring, banks, external_images, settings
from tests.domain.helpers import ADMIN_ID, definition, make_bank, make_quiz

pytestmark = pytest.mark.django_db
URL = "https://a.example/1.png"
OTHER = "https://a.example/2.png"


def image(url=URL, asset="abc"):
    return {"asset": asset, "source": url, "alt": {"cs": "P", "en": "P", "uk": "P"}}


def add(quiz, picture, **values):
    config = definition(("cs",)) | {"image": picture}
    return authoring.save_question(quiz, None, "choice", config, setting_values=values or None)


def external(quiz):
    settings.set_override(EXTERNAL_IMAGE_MODE, quiz, "external", admin_id=ADMIN_ID)


def test_copies_are_not_listed():
    quiz = make_quiz()
    add(quiz, image())
    assert external_images.addresses_of(quiz) == []


def test_an_uploaded_image_is_not_listed():
    quiz = make_quiz()
    external(quiz)
    add(quiz, {"asset": "abc", "alt": {"cs": "P"}})
    assert external_images.addresses_of(quiz) == []


def test_an_image_of_the_draft_is_listed():
    quiz = make_quiz()
    external(quiz)
    add(quiz, image())
    assert external_images.addresses_of(quiz) == [URL]


def test_a_question_value_decides():
    quiz = make_quiz()
    add(quiz, image(), **{EXTERNAL_IMAGE_MODE: "external"})
    assert external_images.addresses_of(quiz) == [URL]


def test_an_image_of_the_published_revision_is_listed_after_its_draft_changed():
    quiz = make_quiz()
    external(quiz)
    question = add(quiz, image())
    authoring.publish(quiz, admin_id=ADMIN_ID)
    config = definition(("cs",)) | {"image": image(OTHER)}
    authoring.save_question(quiz, question, "choice", config)
    assert external_images.addresses_of(quiz) == [URL, OTHER]


def test_an_image_with_no_copy_is_listed_in_copy_mode():
    quiz = make_quiz()
    add(quiz, image(asset=None))
    assert external_images.addresses_of(quiz) == [URL]


def test_draw_pools_are_included():
    quiz = make_quiz()
    external(quiz)
    bank = make_bank()
    banks.save_question(
        bank,
        None,
        "choice",
        definition(("cs", "en", "uk")) | {"image": image()},
        locales=("cs", "en", "uk"),
        tags=(),
    )
    authoring.save_draw(quiz, None, bank_id=str(bank.id), tag="", count=1, points=1, position=0)
    assert external_images.addresses_of(quiz) == [URL]


def test_a_draw_on_a_deleted_bank_is_skipped():
    quiz = make_quiz()
    bank = make_bank()
    banks.save_question(
        bank,
        None,
        "choice",
        definition(("cs", "en", "uk")),
        locales=("cs", "en", "uk"),
        tags=(),
    )
    authoring.save_draw(quiz, None, bank_id=str(bank.id), tag="", count=1, points=1, position=0)
    bank.questions.all().delete()
    bank.delete()
    assert external_images.addresses_of(quiz) == []


def test_each_address_appears_once():
    quiz = make_quiz()
    external(quiz)
    add(quiz, image())
    add(quiz, image())
    assert external_images.addresses_of(quiz) == [URL]

"""The private link: the final score, and what else settings let the author see (AC-58)."""

import logging
from decimal import Decimal

import pytest

from app.domain import authoring, grading, run_links, settings, tokens
from app.domain.models import AttemptAnswer
from tests.domain.helpers import ADMIN_ID, OPTION_A, add_question, make_quiz
from tests.support.client import FormClient
from tests.support.photos import Player, photo_quiz, run_of, upload

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


def text(response):
    return response.content.decode()


def played(quiz=None, run=None, **fields):
    run = run or run_of(quiz or photo_quiz())
    player = Player(run)
    answer = {f"{player.question('image_answer')}:image": upload()} if player.has_photo() else {}
    player.result = player.submit(answer | fields)
    return player


def link_of(player):
    return "/v/" + text(player.result).split('href="/v/')[1].split('"')[0]


def visible_link(player):
    return f'<a href="{link_of(player)}"' in text(player.result)


def test_link_shown_when_waiting():
    assert visible_link(played())


def test_link_shown_when_more_to_see_and_nothing_waits():
    quiz = photo_quiz()
    authoring.save_question(
        quiz,
        authoring.editable_questions(quiz)[0]["id"],
        "image_answer",
        {"prompt": {"cs": "Vyfoťte"}, "auto": {"right": 10, "total": 10}},
    )
    assert visible_link(played(quiz))


def test_no_link_when_nothing_more():
    quiz = make_quiz()
    add_question(quiz)
    run = run_of(quiz)
    player = Player(run)
    html = text(player.plain({f"{player.question('choice')}:options[]": [OPTION_A]}))
    assert "/v/" not in html and "data-result-link" not in html


def test_link_shows_provisional_then_final_score(logged_in):
    player = played()
    html = text(FormClient().get(link_of(player)))
    assert "2 / 10" in html and "předběžné" in html
    grading.save_manual(AttemptAnswer.objects.get(), Decimal(5), admin_id=ADMIN_ID)
    html = text(FormClient().get(link_of(player)))
    assert "7 / 10" in html and "předběžné" not in html


def test_own_answers_only_at_participant_or_public():
    quiz = photo_quiz(plain=True)
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    player = Player(run_of(quiz))
    fields = {
        f"{player.question('image_answer')}:image": upload(),
        f"{player.question('choice')}:options[]": [OPTION_A],
    }
    player.result = player.submit(fields)
    assert "Ano cs" not in text(FormClient().get(link_of(player)))
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "participant", admin_id=ADMIN_ID)
    html = text(FormClient().get(link_of(player)))
    assert "Ano cs" in html


def test_own_photo_at_author_not_at_admins():
    quiz = photo_quiz()
    player = played(quiz)
    row = AttemptAnswer.objects.get()
    link = link_of(player)
    photo = f"{link}/photo/{row.id}"
    assert photo in text(FormClient().get(link))
    response = FormClient().get(photo)
    assert response.status_code == 200 and response["Content-Type"] == "image/webp"
    settings.set_override("photo_visibility", quiz, "admins", admin_id=ADMIN_ID)
    assert photo not in text(FormClient().get(link))
    assert FormClient().get(photo).status_code == 204


def test_no_correct_answer_unless_reveal_allows():
    quiz = photo_quiz(plain=True)
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "participant", admin_id=ADMIN_ID)
    player = Player(run_of(quiz))
    fields = {
        f"{player.question('image_answer')}:image": upload(),
        f"{player.question('choice')}:options[]": ["bbbb2222"],
    }
    player.result = player.submit(fields)
    html = text(FormClient().get(link_of(player)))
    assert "Ne cs" in html and "Ano cs" not in html and "reveal-correct" not in html
    assert "Správná" not in html


def test_correct_answers_when_the_attempts_reveal_allows():
    quiz = photo_quiz(plain=True)
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "participant", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_MOMENT, quiz, "at_end", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_LEVEL, quiz, "answers", admin_id=ADMIN_ID)
    player = Player(run_of(quiz))
    fields = {
        f"{player.question('image_answer')}:image": upload(),
        f"{player.question('choice')}:options[]": ["bbbb2222"],
    }
    player.result = player.submit(fields)
    html = text(FormClient().get(link_of(player)))
    assert "reveal-correct" in html and "Ano cs" in html


def test_deleted_photo_is_gone_from_the_link(logged_in):
    player = played()
    row = AttemptAnswer.objects.get()
    link = link_of(player)
    logged_in.post(f"/admin/answers/{row.id}/delete")
    html = text(FormClient().get(link))
    assert f"{link}/photo/" not in html and "odstraněna" in html
    assert "2 / 10" in html
    assert FormClient().get(f"{link}/photo/{row.id}").status_code == 204


def test_deleted_test_link_ends_it():
    quiz = photo_quiz()
    authoring.publish(quiz, admin_id=ADMIN_ID)
    test_link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    player = played(run=test_link.run)
    link = link_of(player)
    run_links.delete(test_link, admin_id=ADMIN_ID)
    response = FormClient().get(link)
    assert response.status_code == 200 and "nefunguje" in text(response)


def test_invalid_token_is_200_with_one_message_and_never_logged(caplog):
    with caplog.at_level(logging.DEBUG):
        response = FormClient().get("/v/forged-token-value")
    assert response.status_code == 200 and "nefunguje" in text(response)
    assert "forged-token-value" not in caplog.text
    assert "forged-token-value" not in text(response)
    photo = FormClient().get("/v/forged-token-value/photo/00000000-0000-7000-8000-000000000001")
    assert photo.status_code == 204


def test_attempt_token_is_not_a_result_token():
    player = played()
    token = player.form()["attempt_token"]
    assert "nefunguje" in text(FormClient().get(f"/v/{token}"))
    with pytest.raises(tokens.InvalidToken):
        tokens.verify_result(token)


def test_token_of_another_attempt_gets_no_photo():
    first = played()
    second = played(run=first.attempt.run)
    row = AttemptAnswer.objects.get(attempt=first.attempt)
    assert FormClient().get(f"{link_of(second)}/photo/{row.id}").status_code == 204


def test_noindex_and_no_referrer_and_no_store_on_photo():
    player = played()
    row = AttemptAnswer.objects.get()
    page = FormClient().get(link_of(player))
    assert page["X-Robots-Tag"] == "noindex" and page["Referrer-Policy"] == "no-referrer"
    assert "no-store" in page["Cache-Control"]
    photo = FormClient().get(f"{link_of(player)}/photo/{row.id}")
    assert "no-store" in photo["Cache-Control"] and "private" in photo["Cache-Control"]
    assert photo["Referrer-Policy"] == "no-referrer"


def test_test_attempt_says_it_is_a_test():
    quiz = photo_quiz()
    authoring.publish(quiz, admin_id=ADMIN_ID)
    test_link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    player = played(run=test_link.run)
    assert "mode-bar" in text(FormClient().get(link_of(player)))


def test_quiz_page_has_a_slot_and_result_a_link_for_the_script():
    quiz = photo_quiz()
    player = played(quiz)
    assert f'data-result-quiz="{quiz.slug}"' in text(player.result)
    page = text(FormClient().get(f"/q/{quiz.slug}"))
    assert f'data-result-slot="{quiz.slug}"' in page
    assert "hidden" in page.split("data-result-slot")[1]


def test_quiz_page_after_the_run_ended_still_has_the_slot():
    quiz = photo_quiz()
    run = run_of(quiz)
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert f'data-result-slot="{quiz.slug}"' in text(FormClient().get(f"/q/{quiz.slug}"))


def test_test_attempt_is_not_remembered_for_the_quiz():
    quiz = photo_quiz()
    authoring.publish(quiz, admin_id=ADMIN_ID)
    test_link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    player = played(run=test_link.run)
    assert visible_link(player) and "data-result-quiz" not in text(player.result)


def test_privacy_page_mentions_photos_and_the_stored_link():
    html = text(FormClient().get("/privacy?lang=en"))
    assert "photo" in html and "this browser" in html

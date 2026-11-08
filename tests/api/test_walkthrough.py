"""The public walkthrough of a finished run (AC-60)."""

import pytest

from app.domain import authoring, grading, run_links, settings
from app.domain.models import AttemptAnswer, HiddenAnswerValue
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, OPTION_A, OPTION_B, add_question, make_quiz
from tests.support.client import FormClient
from tests.support.photos import Player, photo_quiz, run_of, upload

pytestmark = pytest.mark.django_db
UNAVAILABLE = "není k dispozici"


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


def text(response):
    return response.content.decode()


def public_answers(quiz):
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "public", admin_id=ADMIN_ID)


def choice_quiz(**fields):
    quiz = make_quiz(**fields)
    add_question(quiz)
    public_answers(quiz)
    return quiz


def text_quiz():
    quiz = make_quiz()
    authoring.save_question(
        quiz,
        None,
        "text",
        {
            "prompt": {"cs": "Hlavní město?"},
            "blanks": [{"id": "aa11aa11", "accepted": {"cs": ["Praha"]}}],
            "ignore_case": True,
            "ignore_spaces": True,
            "ignore_diacritics": False,
        },
    )
    public_answers(quiz)
    return quiz


def play_choice(run, option=OPTION_A):
    player = Player(run)
    return player.plain({f"{player.question('choice')}:options[]": [option]})


def play_text(run, value):
    player = Player(run)
    return player.plain({f"{player.question('text')}:blank_1": value})


def address(run):
    return f"/q/{run.quiz.slug}/r/{run.id}/answers"


def walkthrough(run):
    return text(FormClient().get(address(run)))


def closed(run):
    authoring.close_run(run, admin_id=ADMIN_ID)
    return run


def test_unavailable_during_an_open_run():
    run = run_of(choice_quiz())
    play_choice(run)
    response = FormClient().get(address(run))
    assert response.status_code == 200 and UNAVAILABLE in text(response)
    assert "Ano cs" not in text(response)


def test_unavailable_when_not_public():
    quiz = make_quiz()
    add_question(quiz)
    run = run_of(quiz)
    play_choice(run)
    closed(run)
    assert UNAVAILABLE in walkthrough(run)


def test_unavailable_for_a_run_of_another_quiz_or_a_nonsense_address():
    run = closed(run_of(choice_quiz()))
    other = make_quiz(slug="jiny")
    assert UNAVAILABLE in text(FormClient().get(f"/q/{other.slug}/r/{run.id}/answers"))


def test_counts_without_a_link_to_a_participant():
    run = run_of(choice_quiz())
    play_choice(run)
    play_choice(run)
    play_choice(run, OPTION_B)
    html = walkthrough(closed(run))
    assert "Ano cs 2×" in " ".join(html.split()) and "Ne cs 1×" in " ".join(html.split())
    assert html.index("Ano cs 2×") < html.index("Ne cs 1×")
    assert "/v/" not in html and "attempt" not in html.lower()
    assert str(AttemptAnswer.objects.first().attempt_id) not in html


def test_correct_answer_and_explanation_with_public_answers():
    quiz = choice_quiz()
    question = authoring.editable_questions(quiz)[0]
    authoring.save_question(
        quiz,
        question["id"],
        "choice",
        question["definition"],
        explanation={"cs": "Protože ano."},
    )
    run = run_of(quiz)
    play_choice(run)
    html = walkthrough(closed(run))
    assert "reveal-correct" in html and "Protože ano." in html


def test_text_is_counted_after_the_questions_comparison():
    run = run_of(text_quiz())
    play_text(run, "praha")
    play_text(run, "PRAHA ")
    play_text(run, "Brno")
    html = " ".join(walkthrough(closed(run)).split())
    assert "2×" in html and "Brno 1×" in html


def test_hostile_free_text_is_escaped():
    run = run_of(text_quiz())
    play_text(run, "<script>x</script>")
    html = walkthrough(closed(run))
    assert "<script>x" not in html and "&lt;script&gt;x" in html


def test_test_attempts_never_appear():
    quiz = choice_quiz()
    authoring.publish(quiz, admin_id=ADMIN_ID)
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    play_choice(link.run)
    run_links.cancel(link, admin_id=ADMIN_ID)
    assert UNAVAILABLE in walkthrough(link.run)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    play_choice(run, OPTION_B)
    html = " ".join(walkthrough(closed(run)).split())
    assert "Ne cs 1×" in html and "Ano cs 1×" not in html


def test_hidden_value_is_gone_and_audited(logged_in):
    run = run_of(text_quiz())
    play_text(run, "urážka")
    play_text(run, "Brno")
    closed(run)
    question = AttemptAnswer.objects.first().question_id
    html = text(logged_in.get(address(run)))
    url = f"/admin/runs/{run.id}/answers/hide"
    assert url in html
    response = logged_in.post(url, {"question": question, "key": "urážka", "hidden": "1"})
    assert response.status_code == 302 and response["Location"] == address(run)
    public = walkthrough(run)
    assert "urážka" not in public and "Brno" in public
    event = AuditEvent.objects.get(action="answer.value_hidden")
    assert event.actor_id and "urážka" not in str(event.details_json)
    assert "urážka" not in HiddenAnswerValue.objects.get().value_key


def test_hidden_value_can_be_shown_again(logged_in):
    run = run_of(text_quiz())
    play_text(run, "Brno")
    closed(run)
    question = AttemptAnswer.objects.first().question_id
    url = f"/admin/runs/{run.id}/answers/hide"
    logged_in.post(url, {"question": question, "key": "brno", "hidden": "1"})
    assert "Brno" not in walkthrough(run)
    assert "Brno" in text(logged_in.get(address(run)))
    logged_in.post(url, {"question": question, "key": "brno", "hidden": ""})
    assert "Brno" in walkthrough(run) and HiddenAnswerValue.objects.count() == 0


def test_admin_sees_hide_action_public_does_not(logged_in):
    run = run_of(text_quiz())
    play_text(run, "Brno")
    closed(run)
    assert "/answers/hide" in text(logged_in.get(address(run)))
    assert "/answers/hide" not in walkthrough(run)


def test_hide_needs_login():
    run = closed(run_of(text_quiz()))
    response = FormClient().post(
        f"/admin/runs/{run.id}/answers/hide", {"question": "x", "key": "y", "hidden": "1"}
    )
    assert response.status_code == 302 and "/admin/login" in response["Location"]
    assert HiddenAnswerValue.objects.count() == 0


def played_photo(run):
    player = Player(run)
    player.submit({f"{player.question('image_answer')}:image": upload()})
    return AttemptAnswer.objects.get(attempt=player.attempt)


def test_public_photos_alone_show_prompt_and_approved_photos_no_answers():
    quiz = photo_quiz(plain=True, level="public")
    run = run_of(quiz)
    player = Player(run)
    player.submit(
        {
            f"{player.question('image_answer')}:image": upload(),
            f"{player.question('choice')}:options[]": [OPTION_A],
        }
    )
    row = AttemptAnswer.objects.get()
    grading.set_approved(row, True, admin_id=ADMIN_ID)
    html = walkthrough(closed(run))
    assert "Vyfoťte" in html and f"/photo/{row.id}" in html
    assert "Otázka" not in html and "Ano cs" not in html and "reveal-correct" not in html
    assert "×" not in html
    photo = FormClient().get(f"/q/{quiz.slug}/r/{run.id}/photo/{row.id}")
    assert photo.status_code == 200 and photo["Content-Type"] == "image/webp"
    assert "no-store" in photo["Cache-Control"]


def test_a_photo_question_has_no_correct_answer_to_show():
    quiz = photo_quiz(level="public")
    public_answers(quiz)
    run = run_of(quiz)
    played_photo(run)
    html = walkthrough(closed(run))
    assert "Vyfoťte" in html and "Správná odpověď" not in html


def test_unapproved_photo_is_204_and_absent():
    quiz = photo_quiz(level="public")
    run = run_of(quiz)
    row = played_photo(run)
    html = walkthrough(closed(run))
    assert f"/photo/{row.id}" not in html and "Vyfoťte" in html
    assert FormClient().get(f"/q/{quiz.slug}/r/{run.id}/photo/{row.id}").status_code == 204


def test_photo_refused_during_open_run():
    quiz = photo_quiz(level="public")
    run = run_of(quiz)
    row = played_photo(run)
    grading.set_approved(row, True, admin_id=ADMIN_ID)
    assert FormClient().get(f"/q/{quiz.slug}/r/{run.id}/photo/{row.id}").status_code == 204


def test_photo_of_another_run_is_refused():
    quiz = photo_quiz(level="public")
    run = run_of(quiz)
    row = played_photo(run)
    grading.set_approved(row, True, admin_id=ADMIN_ID)
    closed(run)
    other = authoring.open_run(quiz, admin_id=ADMIN_ID)
    closed(other)
    assert FormClient().get(f"/q/{quiz.slug}/r/{other.id}/photo/{row.id}").status_code == 204


def test_withdrawn_approval_or_lowered_level_hides_a_photo():
    quiz = photo_quiz(level="public")
    run = run_of(quiz)
    row = played_photo(run)
    grading.set_approved(row, True, admin_id=ADMIN_ID)
    closed(run)
    url = f"/q/{quiz.slug}/r/{run.id}/photo/{row.id}"
    assert FormClient().get(url).status_code == 200
    settings.set_override("photo_visibility", quiz, "author", admin_id=ADMIN_ID)
    assert FormClient().get(url).status_code == 204
    assert UNAVAILABLE in walkthrough(run)


def test_newer_revision_shows_its_questions_and_drops_old_answers():
    quiz = choice_quiz()
    run = run_of(quiz)
    play_choice(run)
    question = authoring.editable_questions(quiz)[0]
    authoring.delete_question(quiz, question["id"])
    add_question(quiz, prompt="Nová otázka")
    authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)
    html = walkthrough(closed(run))
    assert "Nová otázka" in html and "1×" not in html


def test_links_appear_on_public_and_admin_pages(logged_in):
    quiz = choice_quiz()
    run = run_of(quiz)
    play_choice(run)
    assert address(run) not in text(FormClient().get(f"/q/{quiz.slug}/r/{run.id}"))
    closed(run)
    assert address(run) in text(FormClient().get(f"/q/{quiz.slug}/r/{run.id}"))
    assert address(run) in text(FormClient().get(f"/q/{quiz.slug}"))
    assert address(run) in text(logged_in.get(f"/admin/runs/{run.id}"))


def test_no_link_when_nothing_is_public(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    run = closed(run_of(quiz))
    assert "/answers" not in text(FormClient().get(f"/q/{quiz.slug}/r/{run.id}"))
    assert "/answers" not in text(logged_in.get(f"/admin/runs/{run.id}"))


def test_settings_page_warns_about_free_text(showing_all):
    logged_in = showing_all
    quiz = make_quiz()
    assert "Volný text" in text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))


def test_prompt_with_blanks_shows_blanks_not_markers():
    quiz = make_quiz()
    authoring.save_question(
        quiz,
        None,
        "text",
        {
            "prompt": {"cs": "{1} a {2}"},
            "blanks": [
                {"id": "aa11aa11", "accepted": {"cs": ["a"]}},
                {"id": "bb22bb22", "accepted": {"cs": ["b"]}},
            ],
        },
    )
    public_answers(quiz)
    run = closed(run_of(quiz))
    html = walkthrough(run)
    assert "{1}" not in html and "___ a ___" in html

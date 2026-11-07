import pytest

from app.api.rendering import result_sources
from app.domain import attempts, authoring, settings
from app.domain.models import Attempt
from tests.api.test_play import Play
from tests.domain.helpers import ADMIN_ID, OPTION_A, OPTION_B, definition, make_quiz

pytestmark = pytest.mark.django_db


def make_run(moment="at_end", level="verdict", locales=("cs",), questions=1, **fields):
    quiz = make_quiz(locales=locales)
    for number in range(questions):
        config = definition(locales, prompt=f"Dotaz{number}")
        authoring.save_question(quiz, None, "choice", config, **fields)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    if moment == "after_each":
        settings.set_override(settings.NAVIGATION_MODE, quiz, "step_back", admin_id=None)
    settings.set_override(settings.REVEAL_MOMENT, quiz, moment, admin_id=None)
    settings.set_override(settings.REVEAL_LEVEL, quiz, level, admin_id=None)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def result_of(client, run, option=OPTION_A, lang="cs"):
    return Play(client, run, lang).submit(option).content.decode()


def test_never_shows_no_list(client):
    assert "reveal-state" not in result_of(client, make_run("never"))


def test_at_end_lists_the_questions_with_a_verdict(client):
    html = result_of(client, make_run(questions=2))
    assert html.count("reveal-state") == 2
    assert "Dotaz0" in html
    assert "Dotaz1" in html
    assert "reveal-correct" not in html


def test_at_end_lists_only_the_given_questions(client):
    run = make_run(questions=2)
    play = Play(client, run)
    kept = play.question_ids[0]
    Attempt.objects.update(selection_json={"items": [{"id": kept, "draw": None}], "seed": None})
    attempt = Attempt.objects.get()
    from app.domain import attempts

    token = attempts._issue(attempt, attempt.started_at + attempts.ATTEMPT_LIFETIME)
    play.fields["attempt_token"] = token
    html = play.submit().content.decode()
    assert "Dotaz0" in html
    assert "Dotaz1" not in html


def test_answers_level_marks_the_correct_answer(client):
    html = result_of(client, make_run(level="answers"), OPTION_B)
    assert "reveal-correct" in html
    assert "reveal-theirs" in html


@pytest.mark.parametrize(("lang", "text"), [("cs", "Protože"), ("uk", "Тому")])
def test_at_end_with_explanations_shows_the_translation(client, lang, text):
    run = make_run(
        level="explanations", locales=("cs", "uk"), explanation={"cs": "Protože", "uk": "Тому"}
    )
    assert text in result_of(client, run, lang=lang)


def test_verdict_level_hides_the_explanation(client):
    run = make_run(level="answers", explanation={"cs": "Protože"})
    assert "Protože" not in result_of(client, run)


def test_trick_question_shows_none_of_the_answers_as_correct(client):
    quiz = make_quiz(locales=("cs",))
    config = definition(("cs",))
    config["correct"] = []
    authoring.save_question(quiz, None, "choice", config)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_MOMENT, quiz, "at_end", admin_id=None)
    settings.set_override(settings.REVEAL_LEVEL, quiz, "answers", admin_id=None)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = result_of(client, run, OPTION_B)
    assert "Žádná z odpovědí" in html


def test_repeated_submission_shows_stored_score_and_list_from_its_answers(client):
    play = Play(client, make_run())
    assert play.submit().status_code == 200
    html = play.submit(OPTION_B).content.decode()
    assert "<strong>1 / 1</strong>" in html
    assert "reveal-wrong" in html


def test_repeated_submission_with_a_malformed_answer_still_answers(client):
    play = Play(client, make_run())
    assert play.submit().status_code == 200
    assert play.submit("forged").status_code == 200


@pytest.mark.parametrize(
    ("option", "text"), [(OPTION_A, "Správně"), (OPTION_B, "Špatně"), (None, "Bez odpovědi")]
)
def test_state_has_text_not_only_colour(client, option, text):
    assert text in result_of(client, make_run(), option)


def test_after_each_shows_the_list_on_the_result_page(client):
    assert "reveal-state" in result_of(client, make_run("after_each"))


def test_escapes_the_explanation(client):
    run = make_run(level="explanations", explanation={"cs": "<script>x"})
    html = result_of(client, run)
    assert "<script>x" not in html
    assert "&lt;script&gt;x" in html


def test_sources_still_follow_their_own_setting(client):
    run = make_run("never", sources=["Kniha"])
    assert "Kniha" in result_of(client, run)


def _two_questions(*overrides):
    quiz = make_quiz()
    for values in overrides:
        authoring.save_question(
            quiz,
            None,
            "choice",
            definition(("cs",)),
            sources=["Kniha"],
            setting_values=values,
        )
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def test_sources_hidden_on_one_question_only(db):
    run = _two_questions({settings.SHOW_SOURCES: "off"}, {})
    attempt = attempts.start(run).attempt
    questions = attempts.questions_of(attempt)
    assert len(result_sources(questions, run.quiz, "cs")) == 1


def test_sources_shown_on_one_question_when_the_quiz_hides_them(db):
    run = _two_questions({settings.SHOW_SOURCES: "on"}, {})
    settings.set_override(settings.SHOW_SOURCES, run.quiz, "off", admin_id=ADMIN_ID)
    questions = attempts.questions_of(attempts.start(run).attempt)
    assert len(result_sources(questions, run.quiz, "cs")) == 1


def test_none_option_set_on_one_question_only(client, db):
    run = _two_questions({settings.NONE_OPTION: "trick_questions"}, {})
    html = client.post(f"/r/{run.id}/start", {"lang": "cs"}).content.decode()
    assert html.count("Žádná z odpovědí") == 1


def test_points_ignore_question_settings(db):
    run = _two_questions({settings.SHOW_SOURCES: "off"}, {})
    assert authoring.latest_published(run.quiz).max_score == 2

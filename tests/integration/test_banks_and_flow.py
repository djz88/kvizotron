import re

import pytest

from app.domain import attempts, authoring, selection, settings
from app.domain.models import Attempt, RunRevision
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_A,
    OPTION_B,
    add_bank_question,
    add_question,
    add_row,
    bank_with,
    make_quiz,
)

pytestmark = pytest.mark.django_db
HTMX = {"HX-Request": "true"}


def hidden(html, name):
    return re.search(rf'name="{name}" value="([^"]*)"', html).group(1)


def run_with_rows(*rows, own=1):
    quiz = make_quiz()
    for _ in range(own):
        add_question(quiz)
    for bank, count, points in rows:
        add_row(quiz, bank, count=count, points=points)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def correct_answers(attempt, option=OPTION_A):
    return {q["id"]: {"options": [option]} for q in attempts.questions_of(attempt)}


def test_every_attempt_has_the_same_maximum_and_full_marks_reach_it():
    run = run_with_rows((bank_with(6), 3, 2))
    for key in range(5):
        started = attempts.start(run)
        given = attempts.questions_of(started.attempt)
        assert len(given) == 4
        result = attempts.submit(
            started.attempt.id,
            started.token,
            correct_answers(started.attempt),
            f"key-{key:08}",
        )
        assert result.earned_points == result.max_points == 7


def test_same_question_in_two_rows_scores_with_its_rows_points():
    bank = bank_with(2)
    run = run_with_rows((bank, 1, 1), (bank, 1, 5), own=0)
    started = attempts.start(run)
    items = started.attempt.selection_json["items"]
    points = {
        item["draw"]: q["settings"]["points"]
        for item, q in zip(items, attempts.questions_of(started.attempt), strict=True)
    }
    assert sorted(points.values()) == [1, 5]
    result = attempts.submit(
        started.attempt.id, started.token, correct_answers(started.attempt), "key-00000001"
    )
    assert result.earned_points == 6
    assert result.max_points == 6


def test_scoring_uses_the_frozen_selection_after_a_new_publication():
    bank = bank_with(1)
    run = run_with_rows((bank, 1, 2))
    started = attempts.start(run)
    answers = correct_answers(started.attempt)
    add_bank_question(bank, prompt="Nová")
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    result = attempts.submit(started.attempt.id, started.token, answers, "key-00000001")
    assert result.earned_points == 3


def test_a_tampered_selection_breaks_the_token():
    run = run_with_rows((bank_with(3), 1, 1))
    started = attempts.start(run)
    selection_json = {**started.attempt.selection_json, "items": []}
    Attempt.objects.filter(pk=started.attempt.pk).update(selection_json=selection_json)
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(started.attempt.id, started.token, {}, "key-00000001")
    assert error.value.code == "invalid_token"


def test_switch_keeps_answers_to_kept_questions_and_settings():
    bank = bank_with(3)
    run = run_with_rows((bank, 2, 1), own=1)
    settings.set_override(settings.REVEAL_MOMENT, run.quiz, "at_end", admin_id=None)
    started = attempts.start(run)
    answers = correct_answers(started.attempt, OPTION_B)
    add_bank_question(bank, prompt="Nová")
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)
    settings.set_override(settings.REVEAL_MOMENT, run.quiz, "never", admin_id=None)
    moved = attempts.switch(started.attempt.id, started.token, answers)
    assert set(moved.answers) == set(answers)
    assert not moved.changed
    new = moved.started.attempt
    assert attempts.flow_of(new)["moment"] == "at_end"
    assert {q["id"] for q in attempts.questions_of(new)} == set(answers)
    assert new.revision.revision_no == 2
    current = RunRevision.objects.get(run=run, active_to__isnull=True)
    assert current.revision == new.revision


def test_public_page_counts_drawn_questions(client):
    run = run_with_rows((bank_with(5), 3, 1), own=2)
    assert client.get(f"/q/{run.quiz.slug}").status_code == 200
    assert selection.count(run.current_revision.snapshot_json) == 5
    assert "5" in client.get(f"/q/{run.quiz.slug}").content.decode()


def test_participant_plays_a_drawn_quiz_through_the_pages(client):
    run = run_with_rows((bank_with(3), 2, 2))
    html = client.post(f"/r/{run.id}/start", headers=HTMX).content.decode()
    assert html.count('class="flow-question"') == 3
    assert html.count("Banka ") == 2
    attempt = Attempt.objects.get()
    action = f"/a/{attempt.id}/submit"
    fields = {
        "attempt_token": hidden(html, "attempt_token"),
        "submission_key": hidden(html, "submission_key"),
    }
    for question in attempts.questions_of(attempt):
        fields[f"{question['id']}:options[]"] = OPTION_A
    result = client.post(action, fields, headers=HTMX).content.decode()
    assert "<strong>5 / 5</strong>" in result

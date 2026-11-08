"""AC-84: statistics of a run and a comparison of a quiz's runs, without test attempts."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain import authoring, run_links, run_stats
from app.domain.models import Attempt, AttemptAnswer, Participant, QuizRun
from tests.domain.helpers import ADMIN_ID, OPTION_B, add_question, published_quiz

pytestmark = pytest.mark.django_db
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def a_run(quiz=None, profile="answers"):
    return authoring.open_run(
        quiz or published_quiz(questions=2), admin_id=ADMIN_ID, data={"profile": profile}
    )


def person(run):
    return Participant.objects.create(run=run, anonymous_key_hash=f"h{Participant.objects.count()}")


def attempt(run, who, score=None, status=Attempt.Status.SUBMITTED, revision=None, answers=()):
    revision = revision or run.current_revision
    found = Attempt.objects.create(
        run=run,
        participant=who,
        revision=revision,
        status=status,
        submitted_at=T0 if status in Attempt.FINISHED else None,
        score=None if score is None else Decimal(score),
        max_score=revision.max_score,
    )
    for question_id, points in answers:
        AttemptAnswer.objects.create(
            attempt=found, question_id=question_id, answer_json={}, auto_points=Decimal(points)
        )
    return found


def ids(run):
    return [q["id"] for q in run.current_revision.snapshot_json["questions"]]


def known(run):
    """3 participants, 5 started, 4 submitted (one pending), 1 switched, 1 unsent."""
    a, b, c = person(run), person(run), person(run)
    first, second = ids(run)
    attempt(run, a, 2, answers=[(first, 1), (second, 1)])
    attempt(run, a, 1, answers=[(first, 1), (second, 0)])
    attempt(run, b, 0, answers=[(first, 0)])
    attempt(run, c, 1, status=Attempt.Status.PENDING_GRADING, answers=[(second, 1)])
    attempt(run, None, None, status=Attempt.Status.SWITCHED)
    attempt(run, None, None, status=Attempt.Status.IN_PROGRESS)


def test_counts_on_a_known_data_set():
    run = a_run()
    known(run)
    found = run_stats.of_run(run)
    assert (found.participants, found.started, found.submitted) == (3, 5, 4)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run_stats.of_run(run).unsent == 1


def test_summary_and_bands():
    run = a_run()
    known(run)
    summary = run_stats.of_run(run).summary
    assert summary.count == 4
    assert summary.average == Decimal("1.00")
    assert summary.median == Decimal("1.00")
    assert (summary.lowest, summary.highest) == (Decimal(0), Decimal(2))
    assert summary.bands == (1, 0, 0, 0, 0, 2, 0, 0, 0, 1)


def test_per_question_under_answers():
    run = a_run()
    known(run)
    first, second = run_stats.of_run(run).questions
    assert [first.question_id, second.question_id] == ids(run)
    assert (first.answered, first.average, first.full_share) == (3, Decimal("0.67"), 67)
    assert (second.answered, second.average, second.full_share) == (3, Decimal("0.67"), 67)


def test_per_question_absent_under_score_with_reason():
    run = a_run(profile="score")
    known(run)
    found = run_stats.of_run(run)
    assert found.questions is None and found.questions_reason == "profile"
    assert found.summary.count == 4


def test_stateless_run_has_only_the_count():
    run = a_run(profile="none")
    QuizRun.objects.filter(pk=run.pk).update(stateless_submitted=7)
    run.refresh_from_db()
    found = run_stats.of_run(run)
    assert found.submitted == 7
    assert found.summary is None and found.questions is None and found.participants == 0


def test_test_attempts_excluded():
    quiz = published_quiz(questions=2)
    link = run_links.create(quiz, quiz.revisions.get(), expires_at=None, admin_id=ADMIN_ID)
    attempt(link.run, None, 2)
    run = a_run(quiz)
    assert run_stats.of_run(run).submitted == 0
    assert [row.submitted for row in run_stats.comparison(quiz)] == [0]


def test_split_by_revision():
    run = a_run()
    attempt(run, person(run), 2)
    question_id = ids(run)[0]
    add_question(run.quiz, OPTION_B, question_id=question_id)
    new = authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    run.refresh_from_db()
    attempt(run, person(run), 1, revision=new)
    found = run_stats.of_run(run)
    assert [(no, summary.count) for no, summary in found.by_revision] == [(1, 1), (2, 1)]
    assert run_stats.of_run(a_run(published_quiz("jiny"))).by_revision == []


def test_comparison_of_runs():
    quiz = published_quiz(questions=2)
    first = a_run(quiz)
    attempt(first, person(first), 2)
    attempt(first, person(first), 1)
    authoring.close_run(first, admin_id=ADMIN_ID)
    second = a_run(quiz)
    attempt(second, person(second), 2)
    rows = run_stats.comparison(quiz)
    assert [row.run_no for row in rows] == [2, 1]
    assert [(row.participants, row.submitted, row.average, row.percent) for row in rows] == [
        (1, 1, Decimal("2.00"), 100),
        (2, 2, Decimal("1.50"), 75),
    ]
    assert rows[1].closed_at is not None and rows[0].closed_at is None

"""AC-112: statistics and the comparison of runs read a deleted run's summary."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain import authoring, retention, run_stats
from app.domain.models import Attempt, AttemptAnswer, Participant
from tests.domain.helpers import ADMIN_ID, OPTION_B, add_question, published_quiz

pytestmark = pytest.mark.django_db
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def filled(profile="answers"):
    run = authoring.open_run(
        published_quiz(questions=2), admin_id=ADMIN_ID, data={"profile": profile}
    )
    first, second = [q["id"] for q in run.current_revision.snapshot_json["questions"]]
    a = Participant.objects.create(run=run, anonymous_key_hash="a")
    b = Participant.objects.create(run=run, anonymous_key_hash="b")
    for who, score, answers in [
        (a, "2", [(first, 1), (second, 1)]),
        (a, "1", [(first, 1), (second, 0)]),
        (b, "1", [(first, 0)]),
    ]:
        attempt = Attempt.objects.create(
            run=run,
            participant=who,
            revision=run.current_revision,
            status=Attempt.Status.SUBMITTED,
            submitted_at=T0,
            score=Decimal(score),
            max_score=run.current_revision.max_score,
        )
        if profile != "score":
            for question_id, points in answers:
                AttemptAnswer.objects.create(
                    attempt=attempt,
                    question_id=question_id,
                    answer_json={},
                    auto_points=Decimal(points),
                )
    Attempt.objects.create(
        run=run, participant=b, revision=run.current_revision, status=Attempt.Status.IN_PROGRESS
    )
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    return run


def purge(run):
    assert retention.purge_run(run, trigger="automatic", admin_id=None) is True
    run.refresh_from_db()


@pytest.mark.parametrize("profile", ["answers", "detailed", "score"])
def test_of_run_is_the_same_before_and_after(profile):
    """AC-112."""
    run = filled(profile)
    before = run_stats.of_run(run)

    purge(run)

    assert run_stats.of_run(run) == before


def test_the_split_by_revision_is_frozen_with_several_revisions():
    """AC-112: a run that moved to a new revision keeps one summary for each after the purge."""
    run = authoring.open_run(
        published_quiz(questions=2), admin_id=ADMIN_ID, data={"profile": "answers"}
    )
    first_revision = run.current_revision
    first, second = [q["id"] for q in first_revision.snapshot_json["questions"]]
    add_question(run.quiz, OPTION_B, question_id=first)
    newest = authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    run.refresh_from_db()
    for number, (revision, score) in enumerate([(first_revision, "2"), (newest, "1")]):
        who = Participant.objects.create(run=run, anonymous_key_hash=f"r{number}")
        attempt = Attempt.objects.create(
            run=run,
            participant=who,
            revision=revision,
            status=Attempt.Status.SUBMITTED,
            submitted_at=T0,
            score=Decimal(score),
            max_score=revision.max_score,
        )
        AttemptAnswer.objects.create(
            attempt=attempt, question_id=second, answer_json={}, auto_points=Decimal(score)
        )
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    before = run_stats.of_run(run)
    assert [no for no, _summary in before.by_revision] == [1, 2]

    purge(run)

    after = run_stats.of_run(run)
    assert after.by_revision == before.by_revision
    assert [(no, summary.count) for no, summary in after.by_revision] == [(1, 1), (2, 1)]
    assert after == before


def test_questions_are_present_where_the_profile_kept_answers():
    """AC-112: and each finds its text again from the run's revisions."""
    run = filled("answers")

    purge(run)

    found = run_stats.of_run(run)
    assert found.questions_reason is None
    assert found.questions
    known = {q["id"]: q for q in run.current_revision.snapshot_json["questions"]}
    for stat in found.questions:
        assert stat.question == known[stat.question_id]
        assert isinstance(stat.average, Decimal)


def test_questions_are_absent_for_profile_score():
    """AC-112."""
    run = filled("score")

    purge(run)

    found = run_stats.of_run(run)
    assert found.questions is None
    assert found.questions_reason == "profile"


def test_a_stateless_run_reads_the_same_after():
    """AC-112."""
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, data={"profile": "none"})
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    before = run_stats.of_run(run)

    purge(run)

    assert run_stats.of_run(run) == before


@pytest.mark.parametrize("profile", ["answers", "score", "none"])
def test_comparison_is_the_same_before_and_after(profile):
    """AC-112."""
    run = filled(profile) if profile != "none" else None
    if run is None:
        run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, data={"profile": "none"})
        authoring.close_run(run, admin_id=ADMIN_ID)
        run.refresh_from_db()
    before = run_stats.comparison(run.quiz)

    purge(run)

    assert run_stats.comparison(run.quiz) == before


def test_comparison_reads_other_runs_as_before():
    """AC-112: a deleted run next to a live one."""
    run = filled("answers")
    later = authoring.open_run(run.quiz, admin_id=ADMIN_ID, data={"profile": "answers"})
    Attempt.objects.create(
        run=later,
        revision=later.current_revision,
        status=Attempt.Status.SUBMITTED,
        submitted_at=T0,
        score=Decimal(1),
        max_score=later.current_revision.max_score,
    )

    purge(run)

    rows = {row.run_id: row for row in run_stats.comparison(run.quiz)}
    assert rows[later.id].submitted == 1
    assert rows[run.id].submitted == 3


def test_freeze_is_json_safe_and_holds_no_question_text():
    """AC-112."""
    run = filled("answers")

    frozen = run_stats.freeze(run_stats.of_run(run))

    assert json.loads(json.dumps(frozen)) == frozen
    for question in frozen["questions"]:
        assert set(question) == {"question_id", "answered", "average", "full_share"}
        assert isinstance(question["average"], str)
    assert isinstance(frozen["summary"]["average"], str)

"""The attempt that counts follows the scoreboard's revision mode (TD-047, ADR-0065, ADR-0063).

Rewards, draws and the pass mark read `results.kept`; it picks as the board picks: under `percent`
and `separate` over all revisions by the percent of each attempt's own revision maximum, under
`latest` only among the attempts of the run's current revision.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import OFFICIAL_ATTEMPT, REVISION_MODE, AttemptFigures
from app.domain import authoring, results, run_links, settings
from app.domain.models import Attempt, Participant
from tests.domain.helpers import ADMIN_ID, OPTION_B, add_question, published_quiz

pytestmark = pytest.mark.django_db
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
MODES = ("percent", "separate", "latest")


def a_run(quiz, **chosen):
    return authoring.open_run(quiz, admin_id=ADMIN_ID, results=chosen)


def person(run, name=""):
    return Participant.objects.create(
        run=run, anonymous_key_hash=f"h-{Participant.objects.count()}", display_name=name
    )


def played(run, who, score, minute, *, revision=None, status=Attempt.Status.SUBMITTED):
    revision = revision or run.current_revision
    return Attempt.objects.create(
        run=run,
        participant=who,
        revision=revision,
        status=status,
        submitted_at=T0 + timedelta(minutes=minute),
        score=Decimal(score),
        max_score=revision.max_score,
    )


def switch_revision(run, questions_more=0):
    """A new revision; the open run switches to it and keeps the old one's attempts."""
    question_id = run.current_revision.snapshot_json["questions"][0]["id"]
    add_question(run.quiz, OPTION_B, question_id=question_id)
    for _ in range(questions_more):
        add_question(run.quiz)
    revision = authoring.publish(
        run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH
    )
    run.refresh_from_db()
    return revision


def two_revisions(slug="kviz", **chosen):
    """A run that moved from revision 1 of 10 points to revision 2 of 12 points."""
    run = a_run(published_quiz(slug, questions=10), **chosen)
    old = run.current_revision
    new = switch_revision(run, questions_more=2)
    assert (old.max_score, new.max_score) == (Decimal(10), Decimal(12))
    return run, old, new


def a_and_b(**chosen):
    """A: revision 1, 8/10 = 80 %; B later on revision 2, 9/12 = 75 % with more points."""
    run, old, new = two_revisions(**chosen)
    who = person(run, "Ema")
    first = played(run, who, 8, 1, revision=old)
    second = played(run, who, 9, 2, revision=new)
    return who, first, second


def test_best_counts_by_percent_across_revisions():
    who, attempt_a, _attempt_b = a_and_b(**{OFFICIAL_ATTEMPT: "best", REVISION_MODE: "percent"})
    found = results.kept(who)
    assert found.attempt == attempt_a  # 80 % beats 75 %, though B has more points
    assert results.official_attempt(who) == attempt_a
    assert (found.figures.score, found.figures.max_score, found.count) == (
        Decimal(8),
        Decimal(10),
        2,
    )
    (row,) = results.board(who.run, audience="admin", locale="cs").tables[0].rows
    assert row.attempt_id == str(attempt_a.id)  # the attempt the board counts


def test_separate_mode_counts_like_percent():
    """One counted attempt per participant over all revisions: a participant wins only once."""
    who, attempt_a, _attempt_b = a_and_b(**{OFFICIAL_ATTEMPT: "best", REVISION_MODE: "separate"})
    assert results.kept(who).attempt == attempt_a
    assert results.official_attempt(who) == attempt_a


def test_latest_counts_only_the_current_revision():
    run, old, new = two_revisions(**{OFFICIAL_ATTEMPT: "best", REVISION_MODE: "latest"})
    assert run.current_revision_id == new.id
    jan = person(run, "Jan")
    played(run, jan, 10, 1, revision=old)
    assert results.kept(jan) is None
    assert results.official_attempt(jan) is None
    ema = person(run, "Ema")
    played(run, ema, 8, 2, revision=old)
    current = played(run, ema, 3, 3, revision=new)  # fewer points and a lower percent
    found = results.kept(ema)
    assert (found.attempt, found.count) == (current, 1)
    assert results.official_attempt(ema) == current
    (row,) = results.board(run, audience="admin", locale="cs").tables[0].rows
    assert row.attempt_id == str(current.id)  # the attempt the board counts; Jan has no row


def test_waiting_looks_only_at_the_attempts_the_mode_counts():
    """Under latest an older revision's attempt waiting for grading can never count."""
    for slug, mode, waiting in (("p", "percent", True), ("l", "latest", False)):
        run, old, new = two_revisions(slug, **{OFFICIAL_ATTEMPT: "best", REVISION_MODE: mode})
        who = person(run)
        played(run, who, 5, 1, revision=old, status=Attempt.Status.PENDING_GRADING)
        submitted = played(run, who, 6, 2, revision=new)
        found = results.kept(who)
        assert (found.attempt, found.waiting, found.count) == (submitted, waiting, 1), mode


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("rule", "index", "score"),
    [("first", 0, 5), ("best", 1, 9), ("last", 2, 4), ("average", 2, 6)],
)
def test_one_revision_is_unchanged(mode, rule, index, score):
    """A run that never switched revision counts exactly as by points."""
    run = a_run(
        published_quiz(f"one-{mode}-{rule}", questions=10),
        **{OFFICIAL_ATTEMPT: rule, REVISION_MODE: mode},
    )
    who = person(run)
    made = [played(run, who, points, minute) for minute, points in enumerate((5, 9, 4), 1)]
    found = results.kept(who)
    assert (found.attempt, found.count, found.rule) == (made[index], 3, rule)
    assert (found.figures.score, found.figures.max_score) == (Decimal(score), Decimal(10))


def test_average_keeps_its_figures():
    """Picked as the board picks; the figures stay the mean of points over the mean of maxima."""
    who, _attempt_a, attempt_b = a_and_b(**{OFFICIAL_ATTEMPT: "average", REVISION_MODE: "percent"})
    found = results.kept(who)
    assert (found.attempt, found.count) == (attempt_b, 2)  # the last submitted
    # 8.5 of 11 (77.27 %), not the board's mean of percents (77.5 %)
    assert found.figures == AttemptFigures(
        score=Decimal("8.5"), max_score=Decimal(11), correct=0, questions=11
    )
    run, old, new = two_revisions(
        "avg-latest", **{OFFICIAL_ATTEMPT: "average", REVISION_MODE: "latest"}
    )
    who = person(run)
    played(run, who, 8, 1, revision=old)
    current = played(run, who, 9, 2, revision=new)
    found = results.kept(who)
    assert (found.attempt, found.count) == (current, 1)
    assert found.figures == AttemptFigures(
        score=Decimal(9), max_score=Decimal(12), correct=0, questions=12
    )


def test_a_test_run_counts_by_the_quiz_rules():
    """A test run follows the quiz as it is now and keeps its one revision as the current one."""
    quiz = published_quiz("test-run", questions=10)
    settings.set_override(OFFICIAL_ATTEMPT, quiz, "last", admin_id=ADMIN_ID)
    settings.set_override(REVISION_MODE, quiz, "latest", admin_id=ADMIN_ID)
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    add_question(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)  # newer than the test run's revision
    run = link.run
    who = person(run)
    played(run, who, 9, 1)
    last = played(run, who, 4, 2)
    found = results.kept(who)
    assert (found.attempt, found.rule, found.count) == (last, "last", 2)


@pytest.mark.parametrize(
    ("member_mode", "main_mode", "ema_counts", "jan_counts"),
    [("latest", "percent", False, True), ("percent", "latest", True, False)],
)
def test_a_shared_board_member_counts_by_its_own_mode(
    member_mode, main_mode, ema_counts, jan_counts
):
    """Each run of a shared board counts by its own revision mode, not the main run's."""
    quiz = published_quiz("shared", questions=10)
    member = a_run(quiz, **{REVISION_MODE: member_mode})
    ema = person(member, "Ema")
    old = played(member, ema, 8, 1)  # only on the member's first revision
    switch_revision(member, questions_more=2)
    authoring.close_run(member, admin_id=ADMIN_ID)
    main = a_run(quiz, **{REVISION_MODE: main_mode})
    jan = person(main, "Jan")
    own = played(main, jan, 9, 2)  # only on the main run's first revision
    switch_revision(main)
    results.share_board(main, [member], admin_id=ADMIN_ID)
    member.refresh_from_db()
    assert member.board_main_id == main.id
    assert results.official_attempt(ema) == (old if ema_counts else None)
    assert results.official_attempt(jan) == (own if jan_counts else None)

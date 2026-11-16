"""AC-111, AC-113: what the pages say about a run whose data were deleted, none of it an error."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone, translation

from app.api import play
from app.contracts import ARCHIVED_RESULTS, SCOREBOARD_VISIBILITY
from app.domain import (
    authoring,
    data_policy,
    results_export,
    retention,
    run_schedule,
    settings,
    tokens,
    walkthrough,
)
from app.domain.models import (
    Attempt,
    AttemptAnswer,
    Draw,
    DrawEntry,
    Participant,
    QuizRun,
    RewardRule,
)
from tests.api.test_play import HTMX, Play
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db
NAME = "Jana Tajná"
EMAIL = "jana@example.test"
PSEUDONYM = "pseudo-1234"
NOT_PUBLIC = "Výsledky tohoto běhu nejsou veřejné."
NO_WALKTHROUGH = "není k dispozici"
NO_LINK = "Tento odkaz nefunguje."


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


def text(response):
    return response.content.decode()


def a_quiz():
    quiz = published_quiz()
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "public", admin_id=ADMIN_ID)
    return quiz


def open_run(**chosen):
    return authoring.open_run(
        a_quiz(),
        admin_id=ADMIN_ID,
        data={"profile": "answers"},
        results={SCOREBOARD_VISIBILITY: "live"} | chosen,
    )


def played(run):
    who = Participant.objects.create(
        run=run, anonymous_key_hash="a", display_name=NAME, email=EMAIL
    )
    found = Attempt.objects.create(
        run=run,
        participant=who,
        revision=run.current_revision,
        status=Attempt.Status.SUBMITTED,
        submitted_at=timezone.now(),
        score=Decimal(1),
        max_score=run.current_revision.max_score,
    )
    AttemptAnswer.objects.create(
        attempt=found,
        question_id=run.current_revision.snapshot_json["questions"][0]["id"],
        answer_json={},
        auto_points=Decimal(1),
    )
    return found


def drawn(run, who):
    """A published winner: only the pseudonym outlives the participant."""
    rule = RewardRule.objects.create(
        quiz=run.quiz, run=run, kind=RewardRule.Kind.DRAW, winners=1, winners_public=True
    )
    draw = Draw.objects.create(
        run=run,
        rule=rule,
        action=Draw.Action.DRAW,
        admin_id=ADMIN_ID,
        eligible_count=1,
        eligible_set_hash="h",
        algorithm="a",
        rules_version="v",
    )
    DrawEntry.objects.create(
        draw=draw, participant=who, pseudonym=PSEUDONYM, position=1, role=DrawEntry.Role.WINNER
    )


def purge(run):
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert retention.purge_run(run, trigger=retention.AUTOMATIC, admin_id=None) is True
    run.refresh_from_db()


def deleted_run(**chosen):
    run = open_run(**chosen)
    drawn(run, played(run).participant)
    purge(run)
    return run


def restored(run):
    run_schedule.restore(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    return run


def board_url(run, rest=""):
    return f"/q/{run.quiz.slug}/r/{run.id}/scoreboard{rest}"


def assert_not_public(response):
    assert response.status_code == 200
    assert NOT_PUBLIC in text(response)
    assert NAME not in text(response)
    assert EMAIL not in text(response)
    assert "every 15s" not in text(response)


@pytest.mark.parametrize(
    "chosen",
    [
        {},
        {ARCHIVED_RESULTS: "on"},
        {SCOREBOARD_VISIBILITY: "after_end"},
        {SCOREBOARD_VISIBILITY: "hidden"},
    ],
)
def test_the_scoreboard_says_the_results_are_not_public(client, chosen):
    """AC-113: also where the results of an archived run would otherwise stay public."""
    run = deleted_run(**chosen)

    assert_not_public(client.get(board_url(run, "?lang=cs")))
    assert_not_public(client.get(board_url(run, "/rows?lang=cs")))


def test_the_scoreboard_of_a_restored_run_stays_unavailable(client):
    """AC-113: restoring brings the run back, not its data."""
    run = restored(deleted_run(**{ARCHIVED_RESULTS: "on"}))

    assert run.status == QuizRun.Status.CLOSED
    assert_not_public(client.get(board_url(run, "?lang=cs")))


def test_the_quiz_page_of_a_restored_run_answers(client):
    """AC-113."""
    run = restored(deleted_run())

    response = client.get(f"/q/{run.quiz.slug}/r/{run.id}?lang=cs")

    assert response.status_code == 200
    assert NAME not in text(response)
    assert f"/r/{run.id}/scoreboard" not in text(response)


def test_the_walkthrough_is_unavailable(client):
    """AC-113."""
    run = open_run()
    played(run)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert walkthrough.available(run)
    retention.purge_run(run, trigger=retention.AUTOMATIC, admin_id=None)
    run.refresh_from_db()

    response = client.get(f"/q/{run.quiz.slug}/r/{run.id}/answers?lang=cs")

    assert response.status_code == 200
    assert NO_WALKTHROUGH in text(response)


def test_the_walkthrough_of_a_restored_run_stays_unavailable(client):
    """AC-113: it is closed again and its answers were public, but nothing is left to show."""
    run = restored(deleted_run())

    assert not walkthrough.available(run)
    response = client.get(f"/q/{run.quiz.slug}/r/{run.id}/answers?lang=cs")

    assert response.status_code == 200
    assert NO_WALKTHROUGH in text(response)


def test_a_private_link_does_not_work_any_more(client):
    """AC-113."""
    run = open_run()
    attempt = played(run)
    token = tokens.issue_result(attempt.pk)
    purge(run)

    response = client.get(f"/v/{token}?lang=cs")

    assert response.status_code == 200
    assert NO_LINK in text(response)


@pytest.fixture
def stranded(client):
    """A participant still on the page when the run ended and its data went."""
    run = open_run()
    player = Play(client, run)
    attempt_id = player.action.split("/")[2]
    purge(run)
    assert not Attempt.objects.filter(pk=attempt_id).exists()
    return run, player, attempt_id


def assert_gone(response):
    assert response.status_code == 410
    with translation.override("cs"):
        assert str(play.MESSAGES["attempt_gone"]) in text(response)


def test_submitting_an_attempt_whose_row_is_gone_gets_the_error_page(client, stranded):
    """AC-113."""
    _run, player, _attempt = stranded

    assert_gone(client.post(player.action, player.fields, headers=HTMX))


def test_resuming_an_attempt_whose_row_is_gone_gets_the_error_page(client, stranded):
    """AC-113: and the browser is told to drop its copy."""
    run, player, attempt_id = stranded

    response = client.post(
        f"/r/{run.id}/resume",
        {"attempt_id": attempt_id, "attempt_token": player.fields["attempt_token"]},
        headers=HTMX,
    )

    assert_gone(response)
    assert response["X-Kvz-Drop-Copy"] == "1"


@pytest.mark.parametrize("action", ["check", "switch"])
def test_other_steps_of_play_get_the_error_page(client, stranded, action):
    """AC-113."""
    _run, player, attempt_id = stranded

    assert_gone(client.post(f"/a/{attempt_id}/{action}", player.fields, headers=HTMX))


def test_the_time_left_of_a_gone_attempt_answers(client, stranded):
    """AC-113: the countdown on an open page."""
    _run, player, attempt_id = stranded

    response = client.post(f"/a/{attempt_id}/time", player.fields, headers=HTMX)

    assert response.status_code == 410
    assert response.json() == {"error": "attempt_gone"}


def test_an_export_holds_only_the_submitted_count():
    """AC-111."""
    run = deleted_run()

    assert results_export.offered([run]) == {"questions": 1}
    assert data_policy.of(run)[data_policy.PROFILE] == "none"
    (table,) = results_export.tables([run], ["questions"], "en", photos=False)
    (row,) = table.rows
    assert row["submitted"] == "1"
    assert {name for name, value in row.items() if value} == {"run", "revision", "submitted"}


def test_the_draw_page_shows_the_pseudonym(logged_in):
    """AC-113: the only trace of a winner, and nothing that names them."""
    run = deleted_run()

    response = logged_in.get(f"/admin/runs/{run.id}/draw?lang=en")

    assert response.status_code == 200
    assert PSEUDONYM in text(response)
    assert NAME not in text(response)
    assert EMAIL not in text(response)


def test_the_rewards_page_answers(logged_in):
    """AC-113."""
    run = deleted_run()

    response = logged_in.get(f"/admin/runs/{run.id}/rewards?lang=en")

    assert response.status_code == 200
    assert NAME not in text(response)


def test_the_published_winner_is_not_on_the_public_board(client):
    """AC-113: a pseudonym is for the admin's page."""
    run = restored(deleted_run())

    response = client.get(board_url(run, "?lang=cs"))

    assert PSEUDONYM not in text(response)


def test_the_run_page_says_a_deleted_run_refuses_the_period(logged_in):
    """AC-113: a refusal on the page, not an error."""
    run = deleted_run()

    response = logged_in.post(f"/admin/runs/{run.id}/period", {"retention_period": "3y"})

    assert response.status_code == 200
    assert "smazaná" in text(response)
    run.refresh_from_db()
    assert data_policy.of(run)[data_policy.PERIOD] != "3y"


def test_the_run_page_refuses_a_period_needing_confirmation(logged_in):
    """AC-114: the form has no confirmation yet, so the period stays and the page answers."""
    run = open_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    QuizRun.objects.filter(pk=run.pk).update(
        closed_at=timezone.now() - timedelta(days=100),
        retention_json={"profile": "answers", "period": "1y"},
    )

    response = logged_in.post(f"/admin/runs/{run.id}/period", {"retention_period": "30d"})

    assert response.status_code == 200
    run.refresh_from_db()
    assert data_policy.of(run)[data_policy.PERIOD] == "1y"
    assert run.data_deleted_at is None

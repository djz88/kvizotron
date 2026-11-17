"""AC-06, AC-81: the admin sees every board with names and picks how revisions are shown."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.urls import NoReverseMatch, reverse

from app.contracts import OFFICIAL_ATTEMPT, REVISION_MODE, SCOREBOARD_VISIBILITY
from app.domain import authoring, results
from app.domain.models import Attempt, Participant
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, OPTION_B, add_question, published_quiz

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def played(run, name, score=1, revision=None):
    who = Participant.objects.create(
        run=run, anonymous_key_hash=f"h{Participant.objects.count()}", display_name=name
    )
    revision = revision or run.current_revision
    return Attempt.objects.create(
        run=run,
        participant=who,
        revision=revision,
        status=Attempt.Status.SUBMITTED,
        submitted_at=datetime(2030, 1, 1, 10, 0, tzinfo=UTC),
        score=Decimal(score),
        max_score=revision.max_score,
    )


def switch_revision(run, more=0):
    question_id = run.current_revision.snapshot_json["questions"][0]["id"]
    add_question(run.quiz, OPTION_B, question_id=question_id, prompt="Nová otázka")
    for _ in range(more):
        add_question(run.quiz)
    decision = authoring.Decision.LET_FINISH
    revision = authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=decision)
    run.refresh_from_db()
    return revision


def test_admin_sees_names_on_hidden_board(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    played(run, "Ema")
    html = text(logged_in.get(f"/admin/runs/{run.id}/scoreboard?lang=en"))
    assert "Ema" in html
    assert f"/q/{run.quiz.slug}/r/{run.id}/scoreboard" in html


def test_display_form_saves_and_ignores_fixed_keys(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    logged_in.post(
        f"/admin/runs/{run.id}/scoreboard/settings",
        {SCOREBOARD_VISIBILITY: "after_end", OFFICIAL_ATTEMPT: "first"},
    )
    run.refresh_from_db()
    assert results.of(run)[SCOREBOARD_VISIBILITY] == "after_end"
    assert results.of(run)[OFFICIAL_ATTEMPT] == "best"


def test_run_page_offers_the_three_revision_modes(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/runs/{run.id}/scoreboard?lang=en"))
    assert f'<select name="{REVISION_MODE}">' in html
    assert '<option value="percent" selected>One table by percent</option>' in html
    assert '<option value="separate">One table per revision</option>' in html
    assert '<option value="latest">Only the latest revision</option>' in html
    assert "Merge the revisions" not in html


def test_admin_can_switch_an_ended_run_to_separate_tables(logged_in):
    """AC-06: one table by percent by default, switched on the run page also after the end."""
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    played(run, "Ema", 0, run.current_revision)
    new = switch_revision(run, more=1)
    played(run, "Jan", 1, new)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert len(results.board(run, audience="admin", locale="cs").tables) == 1
    response = logged_in.post(
        f"/admin/runs/{run.id}/scoreboard/settings", {REVISION_MODE: "separate"}
    )
    assert response.status_code == 302
    run.refresh_from_db()
    tables = results.board(run, audience="admin", locale="cs").tables
    assert [table.max_score for table in tables] == [Decimal(2), Decimal(1)]
    html = text(logged_in.get(f"/admin/runs/{run.id}/scoreboard?lang=en"))
    assert '<option value="separate" selected>' in html
    assert AuditEvent.objects.filter(action="run.scoreboard_changed").count() == 1


def test_merge_routes_are_gone(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    for name in ("admin_run_merge", "admin_run_unmerge"):
        with pytest.raises(NoReverseMatch):
            reverse(name, args=[run.id])
    assert logged_in.get(f"/admin/runs/{run.id}/merge").status_code == 404
    assert logged_in.post(f"/admin/runs/{run.id}/unmerge").status_code == 404

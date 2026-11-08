"""AC-06, AC-81: the admin sees every board with names, and merges revisions knowingly."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.contracts import OFFICIAL_ATTEMPT, SCOREBOARD_VISIBILITY
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
    html = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert "Ema" in html
    assert f"/q/{run.quiz.slug}/r/{run.id}/scoreboard" in html


def test_display_form_saves_and_ignores_fixed_keys(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    logged_in.post(
        f"/admin/runs/{run.id}/scoreboard",
        {SCOREBOARD_VISIBILITY: "after_end", OFFICIAL_ATTEMPT: "first"},
    )
    run.refresh_from_db()
    assert results.of(run)[SCOREBOARD_VISIBILITY] == "after_end"
    assert results.of(run)[OFFICIAL_ATTEMPT] == "best"


def test_merge_page_shows_differences(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    switch_revision(run)
    html = text(logged_in.get(f"/admin/runs/{run.id}/merge?lang=en"))
    assert "Nová otázka" in html
    assert 'name="confirm"' in html


def test_merge_refused_with_different_max(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    switch_revision(run, more=1)
    html = text(logged_in.get(f"/admin/runs/{run.id}/merge?lang=en"))
    assert "different maximum points" in html and 'name="confirm"' not in html
    response = logged_in.post(f"/admin/runs/{run.id}/merge?lang=en", {"confirm": "1"})
    assert response.status_code == 409
    assert results.revision_mode(run) == "separate"


def test_merge_and_unmerge_through_routes(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    old = run.current_revision
    played(run, "Ema", 0, old)
    new = switch_revision(run)
    played(run, "Jan", 1, new)
    assert logged_in.post(f"/admin/runs/{run.id}/merge", {"confirm": "1"}).status_code == 302
    run.refresh_from_db()
    assert len(results.board(run, audience="admin", locale="cs").tables) == 1
    assert logged_in.post(f"/admin/runs/{run.id}/unmerge").status_code == 302
    run.refresh_from_db()
    assert len(results.board(run, audience="admin", locale="cs").tables) == 2
    assert AuditEvent.objects.filter(action__startswith="run.revisions_").count() == 2


def test_merge_needs_login(client):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    assert client.get(f"/admin/runs/{run.id}/merge").status_code == 302
    assert client.post(f"/admin/runs/{run.id}/merge", {"confirm": "1"}).status_code == 302
    assert results.revision_mode(run) == "separate"

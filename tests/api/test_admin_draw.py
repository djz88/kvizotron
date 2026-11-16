"""AC-12, AC-92: the admin's draw page of a run.

The page shows, per draw rule, why a draw cannot happen yet, or who is eligible with the snapshot's
fingerprint, then the winners, the alternates in order and every record of the history. Only a
POST draws or changes anything; a repeat needs a reason. Winners are published by one switch, which
is audited.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts import ASK_EMAIL, REWARD_SOURCE
from app.domain import (
    attempts,
    authoring,
    clock,
    draws,
    participants,
    retention,
    rewards,
    run_schedule,
    settings,
)
from app.domain.models import Draw, QuizRun, RewardEntitlement, RewardRule
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, OPTION_A, published_quiz
from tests.support.client import FormClient
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
THEME = Path(__file__).resolve().parents[2] / "app/plugins/theme_default/assets"
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
ALGORITHM = "secrets.SystemRandom.sample+sha256"
NOT_CLOSED = "A draw is possible only after the run has closed."
REASON = "Enter a reason, at most 200 characters."


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def text(response):
    return response.content.decode()


def open_with_draw(winners=1, alternates=2, slug="kviz", name="Hlavní cena"):
    quiz = published_quiz(slug)
    data = rewards.RuleData(
        kind="draw",
        winners=winners,
        alternates=alternates,
        texts={"cs": {"name": name, "description": "", "claim": ""}},
    )
    rewards.save_rule(quiz, data, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, rules={ASK_EMAIL: "optional"})
    return run, rewards.rules_of(run)[0]


def play(run, number, name=""):
    who = participants.find_or_create(run, f"key-{number:016d}")
    if name:
        type(who).objects.filter(pk=who.pk).update(
            display_name=name, email=f"{name.lower()}@example.org"
        )
    started = attempts.start(run, participant=who)
    questions = attempts.questions_of(started.attempt)
    answers = {question["id"]: {"options": [OPTION_A]} for question in questions}
    attempts.submit(started.attempt.id, started.token, answers, f"submit-{number:010d}")
    return who


def closed_with(names, first=0, **kwargs):
    run, rule = open_with_draw(**kwargs)
    for number, name in enumerate(names, start=first):
        play(run, number, name)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    return run, rule


def page_of(client, run):
    return client.get(f"/admin/runs/{run.id}/draw?lang=en")


def act(client, run, rule, **data):
    return client.post(f"/admin/runs/{run.id}/draw/{rule.id}?lang=en", data)


def test_nobody_eligible_shows_the_sentence_not_the_button(logged_in):
    run, rule = open_with_draw()
    authoring.close_run(run, admin_id=ADMIN_ID)
    html = text(page_of(logged_in, run))
    assert "Eligible: 0" in html and "Nobody is eligible for this draw." in html
    assert 'value="draw"' not in html


def test_draw_page_lets_fingerprints_and_algorithm_wrap(logged_in):
    run, rule = closed_with(["Alena", "Bohdan"])
    act(logged_in, run, rule, action="draw")
    html = text(page_of(logged_in, run))
    assert html.count('class="draw-wrap"') >= 4 and f'<small class="draw-wrap">{ALGORITHM}' in html
    css = (THEME / "theme.css").read_text()
    assert ".draw-wrap {" in css and "overflow-wrap: anywhere" in css


def test_open_run_shows_refusal(logged_in):
    run, rule = open_with_draw()
    play(run, 1, "Alena")
    response = page_of(logged_in, run)
    assert response.status_code == 200
    html = text(response)
    assert "Hlavní cena" in html and NOT_CLOSED in html
    assert 'value="draw"' not in html
    refused = act(logged_in, run, rule, action="draw")
    assert refused.status_code == 409 and NOT_CLOSED in text(refused)
    # Closed, but keeping nothing: another sentence.
    authoring.close_run(run, admin_id=ADMIN_ID)
    QuizRun.objects.filter(pk=run.pk).update(retention_json={"profile": "none"})
    assert "keeps no scores" in text(page_of(logged_in, run))
    assert not Draw.objects.exists()
    # The run's pages link the draw page when the run has a draw rule.
    for address in (f"/admin/runs/{run.id}?lang=en", f"/admin/runs/{run.id}/rewards?lang=en"):
        assert f"/admin/runs/{run.id}/draw" in text(logged_in.get(address))


def test_preview_then_draw(logged_in, admin_user):
    """AC-12: the admin sees the eligible snapshot (count, fingerprint, people) before drawing."""
    run, rule = closed_with(["Alena", "Bohdan", "Cecílie"])
    snapshot = draws.preview(rule)
    html = text(page_of(logged_in, run))
    assert "Eligible: 3" in html and snapshot.fingerprint in html
    assert "Alena" in html and "Bohdan" in html and "Cecílie" in html
    assert 'value="draw"' in html
    response = act(logged_in, run, rule, action="draw")
    assert response.status_code == 302
    assert response["Location"].startswith(f"/admin/runs/{run.id}/draw")
    (done,) = Draw.objects.all()
    assert done.eligible_set_hash == snapshot.fingerprint and done.admin_id == str(admin_user.pk)
    standing = draws.standing(rule)
    winner = standing.winners[0].participant
    html = text(page_of(logged_in, run))
    winners = html[html.index('id="winners-') :]
    assert winner.display_name in winners
    assert winner.email == f"{winner.display_name.lower()}@example.org"
    assert winner.email in winners
    assert len(standing.alternates) == 2
    assert 'value="draw"' not in html and 'value="redraw"' in html
    again = act(logged_in, run, rule, action="draw")
    assert again.status_code == 409 and "already been drawn" in text(again)
    assert Draw.objects.count() == 1


def test_the_reason_fields_say_not_to_name_people(logged_in):
    """AC-113: the reason stays in the draw history after the data are deleted."""
    run, rule = closed_with(["Alena", "Bohdan", "Cecílie"])
    act(logged_in, run, rule, action="draw")
    html = text(page_of(logged_in, run))
    assert html.count("Do not name people here") == 2


def test_fewer_eligible_than_requested_is_said(logged_in):
    run, rule = closed_with(["Alena"], winners=1, alternates=2)
    assert act(logged_in, run, rule, action="draw").status_code == 302
    assert "Drew 1 of 3" in text(page_of(logged_in, run))


def test_move_up_substitute_redraw_through_page(logged_in):
    run, rule = closed_with(["Alena", "Bohdan", "Cyril", "Dana", "Eva"], alternates=1)
    act(logged_in, run, rule, action="draw")
    first = draws.standing(rule)
    alternate = first.alternates[0].participant_id
    moved = act(
        logged_in, run, rule, action="move_up", entry=first.winners[0].id, reason="Nepřišel"
    )
    assert moved.status_code == 302
    after_move = draws.standing(rule)
    assert after_move.winners[0].participant_id == alternate and after_move.alternates == []
    none_left = act(
        logged_in, run, rule, action="move_up", entry=after_move.winners[0].id, reason="Znovu"
    )
    assert none_left.status_code == 409 and "No alternate" in text(none_left)
    swapped = act(
        logged_in, run, rule, action="substitute", entry=after_move.winners[0].id, reason="Odmítl"
    )
    assert swapped.status_code == 302
    assert draws.standing(rule).winners[0].participant_id not in {
        alternate,
        first.winners[0].participant_id,
    }
    redone = act(logged_in, run, rule, action="redraw", reason="Chybná pravidla")
    assert redone.status_code == 302
    actions = list(Draw.objects.order_by("created_at", "id").values_list("action", flat=True))
    assert actions == ["draw", "move_up", "substitute", "redraw"]
    # A winner's entry of another rule, or a stale one, is not found.
    stale = act(logged_in, run, rule, action="move_up", entry=first.winners[0].id, reason="x")
    assert stale.status_code == 409
    nonsense = act(logged_in, run, rule, action="move_up", entry="nonsense", reason="x")
    assert nonsense.status_code == 404
    assert act(logged_in, run, rule, action="bogus").status_code == 400
    assert Draw.objects.count() == 4


def test_reason_missing_rejected(logged_in):
    run, rule = closed_with(["Alena", "Bohdan", "Cyril"])
    act(logged_in, run, rule, action="draw")
    winner = draws.standing(rule).winners[0]
    for data in (
        {"action": "redraw", "reason": ""},
        {"action": "move_up", "entry": winner.id, "reason": "   "},
        {"action": "substitute", "entry": winner.id, "reason": "x" * 201},
    ):
        response = act(logged_in, run, rule, **data)
        assert response.status_code == 400 and REASON in text(response)
    assert Draw.objects.count() == 1


def test_history_lists_every_record(logged_in):
    """AC-12: the history of repeated draws lists every record with time, admin and reason."""
    run, rule = closed_with(["Alena", "Bohdan", "Cyril"])
    act(logged_in, run, rule, action="draw")
    act(logged_in, run, rule, action="redraw", reason="Chybná <b>pravidla</b>")
    html = text(page_of(logged_in, run))
    history = html[html.index('id="history-') :]
    for record in Draw.objects.all():
        assert record.eligible_set_hash in history
        assert clock.shown(record.created_at) in history
    assert history.count(ALGORITHM) == 2
    assert "First draw" in history and "Redraw" in history and "Superseded" in history
    assert "Chybná &lt;b&gt;pravidla&lt;/b&gt;" in history
    assert "alice" in history  # the admin's login


def test_get_never_draws(logged_in):
    """AC-12: a closed run with players never draws by itself; only a signed-in POST does."""
    run, rule = closed_with(["Alena", "Bohdan"])
    for _ in range(3):
        assert page_of(logged_in, run).status_code == 200
    assert logged_in.get(f"/admin/runs/{run.id}/draw/{rule.id}").status_code == 405
    assert not Draw.objects.exists()
    assert not RewardEntitlement.objects.filter(source="draw").exists()
    # Login is required for both, and the rule must be a draw rule of this run.
    anonymous = FormClient()
    response = anonymous.get(f"/admin/runs/{run.id}/draw")
    assert response.status_code == 302 and "/admin/login" in response["Location"]
    response = anonymous.post(f"/admin/runs/{run.id}/draw/{rule.id}", {"action": "draw"})
    assert response.status_code == 302 and "/admin/login" in response["Location"]
    other_run, other_rule = closed_with(["Cyril"], first=10, slug="jiny")
    assert act(logged_in, run, other_rule, action="draw").status_code == 404
    assert not Draw.objects.exists()


def test_publish_switch_audited(logged_in):
    run, rule = closed_with(["Alena"])
    assert "Publish the winners" in text(page_of(logged_in, run))
    assert act(logged_in, run, rule, action="publish").status_code == 302
    rule.refresh_from_db()
    assert rule.winners_public
    html = text(page_of(logged_in, run))
    assert "Hide the winners" in html and 'value="unpublish"' in html
    assert act(logged_in, run, rule, action="unpublish").status_code == 302
    rule.refresh_from_db()
    assert not rule.winners_public
    switches = AuditEvent.objects.filter(action="draw.winners_public").order_by("id")
    assert [event.details_json["public"] for event in switches] == [True, False]
    assert RewardRule.objects.get(pk=rule.pk).winners_public is False


def test_draw_after_the_deadline_closes_the_run_lazily(logged_in, monkeypatch):
    # ADR-0048: nobody closes the run; the clock middleware does when the next request comes.
    quiz = published_quiz("uzaverka")
    data = rewards.RuleData(
        kind="draw",
        winners=1,
        alternates=0,
        texts={"cs": {"name": "Cena", "description": "", "claim": ""}},
    )
    rewards.save_rule(quiz, data, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    run = run_schedule.open_now(
        quiz, deadline_at=NOW + timedelta(hours=1), limit_sec=None, admin_id=ADMIN_ID
    )
    rule = rewards.rules_of(run)[0]
    play(run, 1, "Alena")
    assert NOT_CLOSED in text(page_of(logged_in, run))
    freeze(monkeypatch, NOW + timedelta(hours=2))
    html = text(page_of(logged_in, run))
    assert NOT_CLOSED not in html and 'value="draw"' in html
    assert act(logged_in, run, rule, action="draw").status_code == 302
    assert Draw.objects.count() == 1


def test_every_action_through_the_page_is_refused_after_the_data_were_deleted(logged_in):
    """AC-12, AC-111: the draw page of a deleted run says why and no POST adds a record."""
    run, rule = closed_with(["Alena", "Bohdan", "Cecílie"])
    act(logged_in, run, rule, action="draw")
    winner = draws.standing(rule).winners[0]
    retention.purge_run(run, trigger="manual", admin_id=ADMIN_ID)
    before = Draw.objects.count()

    assert "keeps no scores" in text(page_of(logged_in, run))
    for data in (
        {"action": "draw"},
        {"action": "redraw", "reason": "Znovu"},
        {"action": "move_up", "entry": winner.id, "reason": "Nepřevzal"},
        {"action": "substitute", "entry": winner.id, "reason": "Nepřevzal"},
    ):
        response = act(logged_in, run, rule, **data)
        assert response.status_code == 409, data
        assert "keeps no scores" in text(response)
    assert Draw.objects.count() == before


def test_history_names_a_deleted_admin_without_its_id(logged_in):
    """AC-169: a draw made by an account deleted since then shows "a deleted admin"."""
    run, rule = closed_with(["Alena", "Bohdan"])
    act(logged_in, run, rule, action="draw")
    gone = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    Draw.objects.update(admin_id=gone)
    html = text(page_of(logged_in, run))
    history = html[html.index('id="history-') :]
    assert gone not in history
    assert "a deleted admin" in history

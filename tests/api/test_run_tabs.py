"""AC-184: a run's parts are pages with their own addresses, under one run header and tab bar."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from app.api import admin_runs, admin_view
from app.contracts import SCOREBOARD_VISIBILITY
from app.domain import authoring, clock, results, retention
from app.domain.models import Attempt, Participant, QuizRun, RewardRule
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def text(response):
    return response.content.decode()


def open_run():
    return authoring.open_run(published_quiz(), admin_id=ADMIN_ID)


def played(run, name, score, minute=0):
    who = Participant.objects.create(
        run=run, anonymous_key_hash=f"h{Participant.objects.count()}", display_name=name
    )
    return Attempt.objects.create(
        run=run,
        participant=who,
        revision=run.current_revision,
        status=Attempt.Status.SUBMITTED,
        submitted_at=T0 + timedelta(minutes=minute),
        score=Decimal(score),
        max_score=run.current_revision.max_score,
    )


def run_with_two_attempts():
    run = open_run()
    played(run, "Ema", 1, 0)
    played(run, "Jan", 0, 1)
    return run


def test_every_tab_has_its_own_address(logged_in):
    """AC-184: each part of a run is a page of its own; the bar marks the current one."""
    run = open_run()
    for path, label in [
        ("", "Overview"),
        ("/attempts", "Attempts"),
        ("/scoreboard", "Scoreboard"),
        ("/statistics", "Statistics"),
        ("/export", "Export"),
    ]:
        html = text(logged_in.get(f"/admin/runs/{run.id}{path}?lang=en"))
        assert re.search(rf'aria-current="page">{label}<', html), path


def test_the_run_header_is_on_every_tab(logged_in):
    """AC-184: every tab shows which run it is, with its status, above the bar."""
    run = open_run()
    for path in ("", "/attempts", "/scoreboard", "/statistics", "/export"):
        html = text(logged_in.get(f"/admin/runs/{run.id}{path}?lang=en"))
        assert 'class="run-head"' in html and 'aria-label="Parts of this run"' in html, path
        assert "chip-live" in html and f'href="/admin/runs/{run.id}/statistics"' in html, path


def test_sections_live_on_their_tab(showing_all):
    """AC-184: each section is on its tab only."""
    run = open_run()
    played(run, "Ema", 1)
    overview = text(showing_all.get(f"/admin/runs/{run.id}?lang=en"))
    assert 'name="deadline_at"' in overview and "Scores by tenths" not in overview
    assert 'name="access_code"' not in overview
    statistics = text(showing_all.get(f"/admin/runs/{run.id}/statistics?lang=en"))
    assert "Scores by tenths" in statistics
    board = text(showing_all.get(f"/admin/runs/{run.id}/scoreboard"))
    assert f'action="/admin/runs/{run.id}/scoreboard/settings"' in board
    assert 'name="access_code"' in text(showing_all.get(f"/admin/runs/{run.id}/settings"))
    attempts = text(showing_all.get(f"/admin/runs/{run.id}/attempts?lang=en"))
    assert "Ema" in attempts and "Scores by tenths" not in attempts
    export = text(showing_all.get(f"/admin/runs/{run.id}/export?lang=en"))
    assert f"/admin/exports/new?quiz={run.quiz_id}&amp;runs={run.id}" in export


def test_draw_and_settings_tabs_show_only_when_they_have_something(logged_in):
    """AC-184: no draw rule, no Draw tab; in Basic no access code, no Settings tab."""
    run = open_run()
    basic = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert f'href="/admin/runs/{run.id}/draw"' not in basic
    assert f'href="/admin/runs/{run.id}/settings"' not in basic
    assert f'href="/admin/runs/{run.id}/rewards"' in basic
    logged_in.cookies[admin_view.COOKIE] = "all"
    every = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert f'href="/admin/runs/{run.id}/settings"' in every


def test_sorting_attempts_stays_on_the_tab(logged_in):
    """AC-184: a header link of the attempts table is relative to the Attempts tab."""
    run = run_with_two_attempts()
    html = text(logged_in.get(f"/admin/runs/{run.id}/attempts"))
    assert 'href="?sort=name&amp;dir=asc"' in html and "#attempts" not in html


def test_an_old_anchor_address_still_opens(logged_in):
    """AC-184: an old bookmark with `#` opens the Overview."""
    run = open_run()
    assert logged_in.get(f"/admin/runs/{run.id}#statistics").status_code == 200


def test_the_scoreboard_settings_post_moved(logged_in):
    """AC-184: the settings form posts to a verb address; the tab address is GET only."""
    run = open_run()
    response = logged_in.post(
        f"/admin/runs/{run.id}/scoreboard/settings", {SCOREBOARD_VISIBILITY: "live"}
    )
    assert response.status_code == 302
    run.refresh_from_db()
    assert results.of(run)[SCOREBOARD_VISIBILITY] == "live"
    assert logged_in.post(f"/admin/runs/{run.id}/scoreboard", {}).status_code == 405


def ended_run(slug="konec"):
    run = authoring.open_run(published_quiz(slug), admin_id=ADMIN_ID)
    QuizRun.objects.filter(pk=run.pk).update(
        status=QuizRun.Status.CLOSED,
        closed_at=timezone.now() - timedelta(days=60),
        retention_json={"profile": "answers", "period": "1y"},
    )
    run.refresh_from_db()
    return run


def test_a_refused_scoreboard_setting_stays_on_its_tab(logged_in):
    """AC-184: a refusal of the scoreboard settings re-renders the Scoreboard tab."""
    run = open_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    authoring.archive_quiz(run.quiz, admin_id=ADMIN_ID)
    response = logged_in.post(
        f"/admin/runs/{run.id}/scoreboard/settings?lang=en", {SCOREBOARD_VISIBILITY: "live"}
    )
    assert response.status_code == 409
    html = text(response)
    assert 'role="alert"' in html and re.search(r'aria-current="page">Scoreboard<', html)


def test_saved_scoreboard_settings_return_to_the_scoreboard_tab(logged_in):
    run = open_run()
    response = logged_in.post(
        f"/admin/runs/{run.id}/scoreboard/settings", {SCOREBOARD_VISIBILITY: "live"}
    )
    assert response["Location"] == f"/admin/runs/{run.id}/scoreboard"


def test_a_new_code_is_shown_on_settings(logged_in):
    """AC-184: a generated code is shown once, on the Settings tab."""
    run = open_run()
    html = text(logged_in.post(f"/admin/runs/{run.id}/code?lang=en", {"action": "generate"}))
    assert "It is shown only now" in html and re.search(r'aria-current="page">Settings<', html)


def test_a_removed_code_returns_to_settings(logged_in):
    run = open_run()
    logged_in.post(f"/admin/runs/{run.id}/code", {"action": "generate"})
    response = logged_in.post(f"/admin/runs/{run.id}/code", {"action": "remove"})
    assert response["Location"] == f"/admin/runs/{run.id}/settings"


def test_the_name_edit_without_javascript_lands_on_attempts(logged_in):
    """AC-184: renaming without JavaScript opens and returns to the Attempts tab."""
    run = open_run()
    participant = played(run, "Ema", 1).participant
    edit = logged_in.get(f"/admin/runs/{run.id}/participants/{participant.id}/name?edit=1")
    assert edit["Location"] == f"/admin/runs/{run.id}/attempts?edit={participant.id}"
    back = logged_in.post(
        f"/admin/runs/{run.id}/participants/{participant.id}/name", {"name": "Nový"}
    )
    assert back["Location"] == f"/admin/runs/{run.id}/attempts"


def test_confirm_pages_cancel_to_their_tab(logged_in):
    """AC-184: Cancel on a confirmation page returns to the tab of its form."""
    quiz = published_quiz()
    deadline = timezone.now() + timedelta(hours=2)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, deadline_at=deadline)
    earlier = clock.form_value(deadline - timedelta(hours=1))
    html = text(logged_in.post(f"/admin/runs/{run.id}/deadline", {"deadline_at": earlier}))
    assert 'name="confirmed"' in html or 'name="confirm"' in html
    assert f'href="/admin/runs/{run.id}"' in html  # cancel → overview
    close = text(logged_in.get(f"/admin/runs/{run.id}/close?lang=en"))
    assert 'name="confirm' in close
    assert f'href="/admin/runs/{run.id}"' in close

    ended = ended_run()
    settings = f'href="/admin/runs/{ended.id}/settings"'
    period = logged_in.post(f"/admin/runs/{ended.id}/period", {"retention_period": "30d"})
    assert 'name="confirm' in text(period) and settings in text(period)
    erase = text(logged_in.post(f"/admin/runs/{ended.id}/delete-data"))
    assert 'name="confirm' in erase and settings in erase


def test_retention_forms_return_to_settings(logged_in):
    """AC-184: a saved period and deleted data return to the Settings tab."""
    run = ended_run()
    period = logged_in.post(f"/admin/runs/{run.id}/period", {"retention_period": "permanent"})
    assert period.status_code == 302
    assert period["Location"] == f"/admin/runs/{run.id}/settings"
    deleted = logged_in.post(f"/admin/runs/{run.id}/delete-data", {"confirm": "1"})
    assert deleted.status_code == 302
    assert deleted["Location"] == f"/admin/runs/{run.id}/settings"
    again = logged_in.post(f"/admin/runs/{run.id}/delete-data", {"confirm": "1"})
    assert again.status_code == 302
    assert again["Location"] == f"/admin/runs/{run.id}/settings"


def open_run_with_draw_rule(slug="los"):
    run = authoring.open_run(published_quiz(slug), admin_id=ADMIN_ID)
    RewardRule.objects.create(quiz=run.quiz, run=run, kind=RewardRule.Kind.DRAW, winners=1)
    return run


def test_rewards_and_draw_carry_the_bar(logged_in):
    """AC-184: Rewards and Draw are tabs of the run, with its header instead of a way back."""
    run = open_run_with_draw_rule()
    rewards = text(logged_in.get(f"/admin/runs/{run.id}/rewards?lang=en"))
    assert re.search(r'aria-current="page">Rewards<', rewards)
    assert "Back to the run" not in rewards and "Run 1" in rewards
    draw = text(logged_in.get(f"/admin/runs/{run.id}/draw?lang=en"))
    assert re.search(r'aria-current="page">Draw<', draw) and "Back to the run" not in draw


def test_draw_is_listed_only_with_a_draw_rule(logged_in):
    run = open_run()
    assert f"/admin/runs/{run.id}/draw" not in text(logged_in.get(f"/admin/runs/{run.id}"))
    with_rule = open_run_with_draw_rule()
    html = text(logged_in.get(f"/admin/runs/{with_rule.id}"))
    assert f'href="/admin/runs/{with_rule.id}/draw"' in html


def test_basic_view_without_a_code_has_no_settings_tab(logged_in):
    """AC-184: in Basic a run without a code has nothing on Settings; the page says so."""
    run = open_run()  # no access code, Basic is the default view
    assert f"/admin/runs/{run.id}/settings" not in text(logged_in.get(f"/admin/runs/{run.id}"))
    html = text(logged_in.get(f"/admin/runs/{run.id}/settings?lang=en"))
    assert "Nothing here in the Basic view. Switch to All." in html


def test_the_empty_sentence_is_only_on_an_empty_settings_tab(logged_in):
    run = open_run()
    logged_in.post(f"/admin/runs/{run.id}/code", {"action": "generate"})
    html = text(logged_in.get(f"/admin/runs/{run.id}/settings?lang=en"))
    assert "Nothing here in the Basic view" not in html
    ended = text(logged_in.get(f"/admin/runs/{ended_run().id}/settings?lang=en"))
    assert "Delete data now" in ended and "Nothing here in the Basic view" not in ended


def test_the_empty_sentence_is_translated(logged_in):
    run = open_run()
    html = text(logged_in.get(f"/admin/runs/{run.id}/settings?lang=cs"))
    assert "Tady v zobrazení Základní nic není. Přepněte na Vše." in html


def test_basic_view_lists_settings_when_data_can_be_deleted(logged_in):
    """AC-184: "Delete data now" stays reachable from the bar in the Basic view."""
    run = ended_run()  # no access code, but its data can be deleted
    html = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert f'href="/admin/runs/{run.id}/settings"' in html


def test_the_current_tab_is_always_in_the_bar(logged_in):
    """AC-184: Settings hidden in Basic is still listed and marked while it is open."""
    run = open_run()
    html = text(logged_in.get(f"/admin/runs/{run.id}/settings?lang=en"))
    assert re.search(r'aria-current="page">Settings<', html)


def test_the_more_list_opens_on_its_tab(logged_in):
    run = open_run()
    html = text(logged_in.get(f"/admin/runs/{run.id}/export?lang=en"))
    assert re.search(r'<details class="tab-more" open>\s*<summary aria-current="page">More<', html)


def test_quick_links_go_to_the_tabs(logged_in):
    """AC-184: the quick links to a running run's statistics and scoreboard are its tabs."""
    run = open_run()
    for page in (f"/admin/quizzes/{run.quiz_id}/runs", f"/admin/quizzes/{run.quiz_id}/edit"):
        html = text(logged_in.get(page))
        assert f"/admin/runs/{run.id}/statistics" in html, page
        assert f"/admin/runs/{run.id}/scoreboard" in html, page
        assert f"/admin/runs/{run.id}#" not in html, page


def test_the_runs_table_links_to_the_tabs(logged_in):
    """AC-184: the links of an ended run in the table of runs are its tabs."""
    run = ended_run()
    html = text(logged_in.get(f"/admin/quizzes/{run.quiz_id}/runs"))
    assert f"/admin/runs/{run.id}/statistics" in html
    assert f"/admin/runs/{run.id}/scoreboard" in html
    assert f"/admin/runs/{run.id}#" not in html


def test_rewards_and_draw_share_the_layout_of_the_other_tabs(logged_in):
    """AC-184: Rewards and Draw have the section panel and its Basic / All switch."""
    run = open_run_with_draw_rule("rozlozeni")
    for path in ("/statistics", "/rewards", "/draw"):
        html = text(logged_in.get(f"/admin/runs/{run.id}{path}?lang=en"))
        assert '<div class="with-panel">' in html, path
        assert '<div class="panel-main">' in html, path
        assert 'action="/admin/view"' in html, path


def test_the_rewards_template_of_a_quiz_keeps_its_layout(logged_in):
    run = open_run()
    html = text(logged_in.get(f"/admin/quizzes/{run.quiz_id}/rewards?lang=en"))
    assert "Rewards of a new run" in html
    assert '<div class="with-panel">' not in html and "run-head" not in html


def test_the_run_bar_wraps_and_the_quiz_bar_does_not_change(logged_in):
    """AC-184: the run's bar carries the class that lets its items wrap instead of scrolling."""
    run = open_run()
    html = text(logged_in.get(f"/admin/runs/{run.id}/export?lang=en"))
    assert re.search(r'<nav class="tabs tabs-wrap" aria-label="Parts of this run">', html)
    assert html.count("tabs-wrap") == 1


def current(html, label):
    return re.search(rf'aria-current="page">{label}<', html) is not None


def test_a_conflicting_scoreboard_setting_stays_on_its_tab(logged_in, monkeypatch):
    """AC-184: a ResultConflict re-renders the Scoreboard tab with 409."""

    def conflict(*args, **kwargs):
        raise results.ResultConflict([], [results.STATELESS])

    monkeypatch.setattr(results, "set_display", conflict)
    run = open_run()
    response = logged_in.post(
        f"/admin/runs/{run.id}/scoreboard/settings?lang=en", {SCOREBOARD_VISIBILITY: "live"}
    )
    html = text(response)
    assert response.status_code == 409 and 'role="alert"' in html and current(html, "Scoreboard")


def test_splitting_the_board_of_an_archived_quiz_stays_on_the_scoreboard(logged_in):
    run = open_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    authoring.archive_quiz(run.quiz, admin_id=ADMIN_ID)
    response = logged_in.post(f"/admin/runs/{run.id}/board/split?lang=en")
    html = text(response)
    assert response.status_code == 409 and 'role="alert"' in html and current(html, "Scoreboard")


def test_a_refused_period_stays_on_settings(logged_in):
    run = ended_run()
    response = logged_in.post(f"/admin/runs/{run.id}/period?lang=en", {"retention_period": "x"})
    html = text(response)
    assert response.status_code == 200 and 'role="alert"' in html and current(html, "Settings")


def test_a_refused_access_code_stays_on_settings(logged_in):
    """AC-184: an empty code, an archived quiz and an ended run all re-render Settings."""
    run = open_run()
    empty = logged_in.post(f"/admin/runs/{run.id}/code?lang=en", {"action": "set"})
    assert empty.status_code == 200 and "Enter a code." in text(empty)
    assert 'role="alert"' in text(empty) and current(text(empty), "Settings")
    ended = ended_run("ukonceny")
    closed = logged_in.post(f"/admin/runs/{ended.id}/code?lang=en", {"action": "generate"})
    assert closed.status_code == 200 and "This run has ended." in text(closed)
    assert 'role="alert"' in text(closed) and current(text(closed), "Settings")
    authoring.archive_quiz(ended.quiz, admin_id=ADMIN_ID)
    archived = logged_in.post(f"/admin/runs/{ended.id}/code?lang=en", {"action": "generate"})
    assert archived.status_code == 409
    assert 'role="alert"' in text(archived) and current(text(archived), "Settings")


def test_a_refused_nickname_without_javascript_stays_on_attempts(logged_in):
    run = open_run()
    participant = played(run, "Ema", 1).participant
    response = logged_in.post(
        f"/admin/runs/{run.id}/participants/{participant.id}/name?lang=en", {"name": ""}
    )
    html = text(response)
    assert response.status_code == 400 and 'role="alert"' in html and current(html, "Attempts")
    typed = logged_in.post(
        f"/admin/runs/{run.id}/participants/{participant.id}/name?lang=en", {"name": "x" * 41}
    )
    assert typed.status_code == 400 and f'value="{"x" * 41}"' in text(typed)


def test_a_failed_data_deletion_stays_on_settings_with_the_bar(logged_in, monkeypatch):
    def fails(*args, **kwargs):
        raise OSError("disk")

    monkeypatch.setattr(retention, "delete_now", fails)
    run = ended_run()
    response = logged_in.post(f"/admin/runs/{run.id}/delete-data?lang=en", {"confirm": "1"})
    html = text(response)
    assert response.status_code == 200 and "could not be finished" in html
    assert 'role="alert"' in html and current(html, "Settings")
    assert 'aria-label="Parts of this run"' in html


def test_the_overview_computes_neither_statistics_nor_the_board(logged_in, monkeypatch):
    """AC-184: each tab computes only what it shows."""

    def forbidden(*args, **kwargs):
        raise AssertionError("computed on the Overview")

    run = run_with_two_attempts()
    monkeypatch.setattr(admin_runs, "_stats", forbidden)
    monkeypatch.setattr(results, "board", forbidden)
    assert logged_in.get(f"/admin/runs/{run.id}?lang=en").status_code == 200
    monkeypatch.undo()
    assert "Scores by tenths" in text(logged_in.get(f"/admin/runs/{run.id}/statistics?lang=en"))


def run_in_state(state, slug):
    run = authoring.open_run(published_quiz(slug), admin_id=ADMIN_ID)
    fields = {
        "OPEN": {},
        "SCHEDULED": {
            "status": QuizRun.Status.SCHEDULED,
            "starts_at": timezone.now() + timedelta(days=1),
        },
        "CLOSED": {"status": QuizRun.Status.CLOSED, "closed_at": timezone.now()},
        "ARCHIVED": {"status": QuizRun.Status.ARCHIVED, "closed_at": timezone.now()},
        "DELETED": {
            "status": QuizRun.Status.CLOSED,
            "closed_at": timezone.now(),
            "data_deleted_at": timezone.now(),
        },
    }[state]
    QuizRun.objects.filter(pk=run.pk).update(**fields)
    return run


ALL_TABS = (
    "",
    "/attempts",
    "/scoreboard",
    "/statistics",
    "/rewards",
    "/draw",
    "/export",
    "/settings",
)


@pytest.mark.parametrize("state", ["OPEN", "SCHEDULED", "CLOSED", "ARCHIVED", "DELETED"])
def test_every_tab_renders_in_every_state(logged_in, state):
    """AC-184: all eight tabs answer 200 in any state; the read-only ones refuse POST."""
    run = run_in_state(state, f"stav-{state.lower()}")
    for path in ALL_TABS:
        assert logged_in.get(f"/admin/runs/{run.id}{path}?lang=en").status_code == 200, path
    for path in ("", "/attempts", "/scoreboard", "/statistics", "/export", "/settings"):
        assert logged_in.post(f"/admin/runs/{run.id}{path}", {}).status_code == 405, path

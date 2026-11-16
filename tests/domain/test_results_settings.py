"""AC-81: scoreboard settings are copied onto the run; display ones may change later."""

import pytest

from app.contracts import (
    OFFICIAL_ATTEMPT,
    SCOREBOARD_LIVE_NAMES,
    SCOREBOARD_SHOW_TIME,
    SCOREBOARD_VISIBILITY,
)
from app.domain import authoring, results, run_links, settings
from app.domain.models import QuizRun
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db


def test_defaults_are_hidden():
    found = results.rules_for_quiz(published_quiz())
    assert found[SCOREBOARD_VISIBILITY] == "hidden"
    assert found[OFFICIAL_ATTEMPT] == "best"


def test_open_copies_result_settings_and_a_seed():
    quiz = published_quiz()
    settings.set_override(SCOREBOARD_VISIBILITY, quiz, "live", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, results={OFFICIAL_ATTEMPT: "first"})
    assert run.results_json[SCOREBOARD_VISIBILITY] == "live"
    assert run.results_json[OFFICIAL_ATTEMPT] == "first"
    assert len(run.results_json["seed"]) == 32
    other = authoring.open_run(published_quiz("jiny"), admin_id=ADMIN_ID)
    assert other.results_json["seed"] != run.results_json["seed"]


def test_quiz_change_after_open_does_not_touch_run():
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    settings.set_override(SCOREBOARD_VISIBILITY, quiz, "live", admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert results.of(run)[SCOREBOARD_VISIBILITY] == "hidden"
    assert not results.needs_participant(run)


def test_a_run_without_stored_values_reads_defaults():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    QuizRun.objects.filter(pk=run.pk).update(results_json={})
    run.refresh_from_db()
    assert results.of(run)[SCOREBOARD_VISIBILITY] == "hidden"
    assert results.revision_mode(run) == "percent"  # AC-06: one table by percent by default


def test_test_run_never_has_a_visible_board():
    quiz = published_quiz()
    settings.set_override(SCOREBOARD_VISIBILITY, quiz, "live", admin_id=ADMIN_ID)
    link = run_links.create(quiz, quiz.revisions.get(), expires_at=None, admin_id=ADMIN_ID)
    assert results.of(link.run)[SCOREBOARD_VISIBILITY] == "hidden"


def test_display_change_on_open_run():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    results.set_display(
        run,
        {
            SCOREBOARD_VISIBILITY: "live",
            SCOREBOARD_LIVE_NAMES: "anonymised",
            SCOREBOARD_SHOW_TIME: "on",
            OFFICIAL_ATTEMPT: "first",
        },
        admin_id=ADMIN_ID,
    )
    run.refresh_from_db()
    found = results.of(run)
    assert found[SCOREBOARD_VISIBILITY] == "live"
    assert found[SCOREBOARD_LIVE_NAMES] == "anonymised"
    assert found[SCOREBOARD_SHOW_TIME] == "on"
    assert found[OFFICIAL_ATTEMPT] == "best"  # fixed once the run opened
    assert results.needs_participant(run)


def test_display_change_audited_without_names():
    from app.kernel.models import AuditEvent

    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    results.set_display(run, {SCOREBOARD_VISIBILITY: "live"}, admin_id=ADMIN_ID)
    event = AuditEvent.objects.get(action="run.scoreboard_changed")
    assert event.details_json == {SCOREBOARD_VISIBILITY: "live"}


def test_display_change_refused_with_profile_none():
    """AC-09: a run that keeps no results cannot show a scoreboard."""
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, data={"profile": "none"})
    with pytest.raises(results.ResultConflict) as error:
        results.set_display(run, {SCOREBOARD_VISIBILITY: "live"}, admin_id=ADMIN_ID)
    assert error.value.keys == [SCOREBOARD_VISIBILITY]


def test_display_change_refused_on_test_run():
    quiz = published_quiz()
    link = run_links.create(quiz, quiz.revisions.get(), expires_at=None, admin_id=ADMIN_ID)
    with pytest.raises(results.ResultConflict):
        results.set_display(link.run, {SCOREBOARD_VISIBILITY: "live"}, admin_id=ADMIN_ID)


def test_open_refused_with_answers_after_each():
    quiz = published_quiz()
    settings.set_override(settings.NAVIGATION_MODE, quiz, "step_back", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=ADMIN_ID)
    with pytest.raises(results.ResultConflict):
        authoring.open_run(quiz, admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"})


def test_conflicts_name_each_setting():
    visible = {SCOREBOARD_VISIBILITY: "live"}
    assert results.conflicts(visible, profile="score", reveal_moment="never") == []
    assert results.conflicts(visible, profile="none", reveal_moment="never") == [
        SCOREBOARD_VISIBILITY
    ]
    assert results.conflicts(
        {"scoreboard_show_duration": "on", "scoreboard_second_sort": "duration"},
        profile="answers",
        reveal_moment="never",
    ) == ["scoreboard_show_duration", "scoreboard_second_sort"]
    assert (
        results.conflicts(
            {"scoreboard_show_duration": "on"}, profile="detailed", reveal_moment="never"
        )
        == []
    )


def test_label_replaces_nn_appends_otherwise_and_falls_back():
    quiz = published_quiz(locales=("cs", "en", "uk"))
    quiz.anonymous_label = {"cs": "Tým NN", "en": "Guest"}
    quiz.save()
    assert results.anonymous_label(quiz, "cs", 3) == "Tým 3"
    assert results.anonymous_label(quiz, "en", 3) == "Guest 3"
    assert results.anonymous_label(quiz, "uk", 3) == "Гравець 3"
    quiz.anonymous_label = {}
    quiz.save()
    assert results.anonymous_label(quiz, "cs", 12) == "Hráč 12"
    assert results.anonymous_label(quiz, "en", 1) == "Player 1"

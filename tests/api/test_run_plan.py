"""Planning a run in admin, next to the one-click start (FR-10)."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from django.utils import translation

from app.contracts import ASK_EMAIL
from app.domain import authoring, participants, run_schedule, settings
from app.domain.models import QuizRun
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz, published_quiz
from tests.support.clock import freeze
from tests.support.requirements import needs_reveal_at_end

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
START = "2030-01-01T18:00"  # Prague: 17:00 UTC
DEADLINE = "2030-01-01T20:00"
START_UTC = datetime(2030, 1, 1, 17, 0, tzinfo=UTC)
DEADLINE_UTC = datetime(2030, 1, 1, 19, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def text(response):
    return response.content.decode()


def plan_url(quiz):
    return f"/admin/quizzes/{quiz.id}/plan?lang=en"


def a_plan(quiz=None, limit=None, deadline=None):
    return run_schedule.plan(
        quiz or published_quiz(),
        starts_at=START_UTC,
        deadline_at=deadline,
        limit_sec=limit,
        admin_id=ADMIN_ID,
    )


def test_the_one_click_start_is_unchanged(logged_in):
    settings.set_global(settings.ATTEMPT_LIMIT, "20", admin_id=None)
    quiz = published_quiz()
    logged_in.post(f"/admin/quizzes/{quiz.id}/runs")
    run = quiz.runs.get()
    assert run.status == QuizRun.Status.OPEN
    assert run.deadline_at is None
    assert run.attempt_limit_sec == 1200


def test_plan_link_sits_next_to_start(logged_in):
    quiz = published_quiz()
    assert f"/admin/quizzes/{quiz.id}/plan" in text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))


def test_a_plan_is_stored_in_the_configured_zone(logged_in):
    quiz = published_quiz()
    response = logged_in.post(
        plan_url(quiz), {"starts_at": START, "deadline_at": DEADLINE, "limit_minutes": "15"}
    )
    run = quiz.runs.get()
    assert response.status_code == 302
    assert run.status == QuizRun.Status.SCHEDULED
    assert (run.starts_at, run.deadline_at) == (START_UTC, DEADLINE_UTC)
    assert run.attempt_limit_sec == 900


def test_empty_start_opens_at_once_with_deadline_and_limit(logged_in):
    quiz = published_quiz()
    logged_in.post(plan_url(quiz), {"starts_at": "", "deadline_at": DEADLINE, "limit_minutes": "5"})
    run = quiz.runs.get()
    assert run.status == QuizRun.Status.OPEN
    assert run.deadline_at == DEADLINE_UTC
    assert run.attempt_limit_sec == 300


def test_limit_is_prefilled_from_inheritance(logged_in):
    quiz = published_quiz()
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "15", admin_id=None)
    assert 'name="limit_minutes" value="15"' in text(logged_in.get(plan_url(quiz)))


def test_empty_limit_means_no_limit_for_this_run(logged_in):
    settings.set_global(settings.ATTEMPT_LIMIT, "20", admin_id=None)
    quiz = published_quiz()
    logged_in.post(plan_url(quiz), {"starts_at": START, "deadline_at": "", "limit_minutes": ""})
    assert quiz.runs.get().attempt_limit_sec is None


@pytest.mark.parametrize(
    ("starts_at", "deadline_at", "limit", "message", "status"),
    [
        ("2030-01-01T09:00", "", "", "already passed", 409),
        (START, "2030-01-01T17:00", "", "after the start", 409),
        (START, "", "1441", "1440", 400),
        ("2030-03-31T02:30", "", "", "does not exist", 400),
        ("nonsense", "", "", "valid time", 400),
    ],
)
def test_refusals_show_a_message(logged_in, starts_at, deadline_at, limit, message, status):
    """A field that does not validate is 400, a refusal of the rules 409, both in an alert."""
    quiz = published_quiz()
    response = logged_in.post(
        plan_url(quiz), {"starts_at": starts_at, "deadline_at": deadline_at, "limit_minutes": limit}
    )
    html = text(response)
    assert response.status_code == status
    assert message in html
    assert 'name="starts_at"' in html
    assert not quiz.runs.exists()


def test_a_plan_with_nothing_published_is_refused(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    response = logged_in.post(
        plan_url(quiz), {"starts_at": START, "deadline_at": "", "limit_minutes": ""}
    )
    assert "Publish the quiz first" in text(response)
    assert not quiz.runs.exists()


def test_a_second_plan_is_refused(logged_in):
    run = a_plan()
    response = logged_in.post(
        plan_url(run.quiz), {"starts_at": START, "deadline_at": "", "limit_minutes": ""}
    )
    assert "already" in text(response)
    assert run.quiz.runs.count() == 1


def test_planned_quiz_shows_start_now_edit_and_cancel(logged_in):
    run = a_plan()
    html = text(logged_in.get(f"/admin/quizzes/{run.quiz_id}/edit"))
    assert f"/admin/runs/{run.id}/plan/start" in html
    assert f"/admin/runs/{run.id}/plan/cancel" in html
    assert f"/admin/runs/{run.id}/plan" in html
    assert f"/admin/quizzes/{run.quiz_id}/plan" not in html


def test_the_header_says_when_it_starts(logged_in):
    run = a_plan()
    assert "2030-01-01 18:00 CET" in text(logged_in.get(f"/admin/quizzes/{run.quiz_id}/edit"))


def test_start_now_opens_it(logged_in):
    run = a_plan()
    response = logged_in.post(f"/admin/runs/{run.id}/plan/start")
    assert response.status_code == 302
    assert QuizRun.objects.get(pk=run.pk).status == QuizRun.Status.OPEN


def test_cancel_removes_it(logged_in):
    run = a_plan()
    logged_in.post(f"/admin/runs/{run.id}/plan/cancel")
    assert not QuizRun.objects.filter(pk=run.pk).exists()


def test_edit_shows_the_plan_and_saves_it(logged_in):
    run = a_plan(limit=600, deadline=DEADLINE_UTC)
    html = text(logged_in.get(f"/admin/runs/{run.id}/plan"))
    assert 'value="2030-01-01T18:00"' in html
    assert 'value="2030-01-01T20:00"' in html
    assert 'name="limit_minutes" value="10"' in html
    logged_in.post(
        f"/admin/runs/{run.id}/plan",
        {"starts_at": "2030-01-01T19:00", "deadline_at": "", "limit_minutes": "3"},
    )
    found = QuizRun.objects.get(pk=run.pk)
    assert (found.starts_at, found.deadline_at, found.attempt_limit_sec) == (
        START_UTC + timedelta(hours=1),
        None,
        180,
    )


def test_edit_needs_a_start(logged_in):
    run = a_plan()
    response = logged_in.post(
        f"/admin/runs/{run.id}/plan", {"starts_at": "", "deadline_at": "", "limit_minutes": ""}
    )
    assert response.status_code == 400
    assert QuizRun.objects.get(pk=run.pk).starts_at == START_UTC


def test_the_plan_page_has_the_clock_and_names_the_zone(logged_in):
    html = text(logged_in.get(plan_url(published_quiz())))
    assert 'id="clock"' in html
    assert "Europe/Prague" in html
    assert 'type="datetime-local"' in html


def test_unmet_requirements_on_a_due_plan_are_shown_on_the_quiz(logged_in, monkeypatch):
    quiz = published_quiz()
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=None)
    run = a_plan(quiz)
    freeze(monkeypatch, START_UTC)
    with needs_reveal_at_end():
        html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert QuizRun.objects.get(pk=run.pk).status == QuizRun.Status.SCHEDULED
    assert "Needs the answers at the end" in html


def test_a_plan_page_refuses_an_archived_quiz(logged_in):
    quiz = published_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    assert logged_in.post(
        plan_url(quiz), {"starts_at": START, "deadline_at": "", "limit_minutes": ""}
    ).status_code in (302, 409)
    assert not quiz.runs.exists()


def test_global_limit_field_is_a_number_not_a_list(logged_in):
    html = text(logged_in.get("/admin/settings"))
    assert 'type="number" name="attempt_limit"' in html
    assert 'min="0"' in html
    assert 'max="1440"' in html


def test_global_limit_is_saved(logged_in):
    logged_in.post("/admin/settings", {"attempt_limit": "25"})
    assert settings.resolve(settings.ATTEMPT_LIMIT) == "25"


def test_global_limit_out_of_range_is_refused(logged_in):
    response = logged_in.post("/admin/settings", {"attempt_limit": "1441"})
    assert response.status_code == 200
    assert settings.resolve(settings.ATTEMPT_LIMIT) == "0"


def test_plan_form_overrides_rules(logged_in):
    quiz = published_quiz()
    logged_in.post(
        plan_url(quiz),
        {"starts_at": START, "deadline_at": "", "limit_minutes": "", "ask_name": "required"},
    )
    run = quiz.runs.get()
    assert run.participant_rules_json["ask_name"] == "required"
    assert run.participant_rules_json["repeat_attempts"] == "allow"


def test_plan_edit_changes_rules(logged_in):
    run = a_plan()
    logged_in.post(
        f"/admin/runs/{run.id}/plan?lang=en",
        {"starts_at": START, "deadline_at": "", "limit_minutes": "", "ask_email": "optional"},
    )
    run.refresh_from_db()
    assert run.participant_rules_json["ask_email"] == "optional"


def test_plan_form_is_prefilled_from_the_quiz_and_explains_cookie(logged_in):
    quiz = published_quiz()
    settings.set_override("repeat_attempts", quiz, "forbid", admin_id=None)
    html = text(logged_in.get(plan_url(quiz)))
    assert 'name="repeat_attempts"' in html
    assert re.search(r'<input type="radio" name="repeat_attempts" value="forbid"[^>]*checked', html)
    assert "does not guarantee" in html


def test_run_page_lists_rules(logged_in):
    quiz = published_quiz()
    settings.set_override("ask_name", quiz, "required", admin_id=None)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/runs/{run.id}/attempts?lang=en"))
    with translation.override("en"):
        labels = [
            str(settings.CATALOGUE[key].label)
            for key in ("repeat_attempts", "ask_name", "ask_email", "ask_when", "duplicate_names")
        ]
        required = str(settings.CATALOGUE["ask_name"].value_labels["required"])
    for label in (*labels, required):
        assert label in html


def test_plan_form_sets_profile_and_period(logged_in):
    quiz = published_quiz()
    logged_in.post(
        plan_url(quiz),
        {
            "starts_at": START,
            "deadline_at": "",
            "limit_minutes": "",
            "data_profile": "detailed",
            "retention_period": "3y",
        },
    )
    assert quiz.runs.get().retention_json == {"profile": "detailed", "period": "3y"}


def test_plan_form_is_prefilled_from_the_quiz_with_a_help_line_per_profile(showing_all):
    logged_in = showing_all
    quiz = published_quiz()
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=None)
    html = text(logged_in.get(plan_url(quiz)))
    assert '<option value="answers" selected>' in html
    assert '<option value="90d" selected>' in html
    assert "attempts table" in html and "rankings by time" in html


def test_plan_edit_changes_profile_and_period(logged_in):
    run = a_plan()
    logged_in.post(
        f"/admin/runs/{run.id}/plan?lang=en",
        {
            "starts_at": START,
            "deadline_at": "",
            "limit_minutes": "",
            "data_profile": "none",
            "retention_period": "30d",
        },
    )
    run.refresh_from_db()
    assert run.retention_json == {"profile": "none", "period": "30d"}


def test_period_editable_on_open_and_ended_run(logged_in):
    from app.kernel.models import AuditEvent

    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    url = f"/admin/runs/{run.id}/period"
    assert logged_in.post(url, {"retention_period": "1y"}).status_code == 302
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert logged_in.post(url, {"retention_period": "permanent"}).status_code == 302
    run.refresh_from_db()
    assert run.retention_json["period"] == "permanent"
    assert [e.details_json for e in AuditEvent.objects.filter(action="run.period_changed")] == [
        {"period": "1y"},
        {"period": "permanent"},
    ]


def test_period_refused_on_test_run(logged_in):
    from app.domain import run_links
    from app.kernel.models import AuditEvent

    quiz = published_quiz()
    revision = authoring.latest_published(quiz)
    run = run_links.create(quiz, revision, expires_at=None, admin_id=ADMIN_ID).run
    response = logged_in.post(f"/admin/runs/{run.id}/period", {"retention_period": "1y"})
    assert response.status_code == 404  # test runs are not in the admin's run list
    assert not AuditEvent.objects.filter(action="run.period_changed").exists()


def test_run_page_shows_profile_and_period(showing_all):
    logged_in = showing_all
    quiz = published_quiz()
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=None)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/runs/{run.id}/settings?lang=en"))
    with translation.override("en"):
        profile = str(settings.CATALOGUE[settings.DATA_PROFILE].value_labels["answers"])
        period = str(settings.CATALOGUE[settings.RETENTION_PERIOD].value_labels["90d"])
    assert profile in html and period in html
    assert f"/admin/runs/{run.id}/period" in html


def test_visibility_needs_answers_profile(logged_in):
    quiz = published_quiz()
    url = f"/admin/quizzes/{quiz.id}/settings?lang=en"
    refused = logged_in.post(
        url,
        {"slug": quiz.slug, "answers_visibility": "participant", "data_profile": "score"},
    )
    assert "keeps all answers" in text(refused)
    assert settings.quiz_override(settings.ANSWERS_VISIBILITY, quiz) is None
    accepted = logged_in.post(
        url,
        {"slug": quiz.slug, "answers_visibility": "participant", "data_profile": "answers"},
    )
    assert accepted.status_code == 302


def test_plan_groups_are_closed_when_nothing_differs(logged_in):
    """AC-87: the plan shows its time fields and what differs from the quiz."""
    html = text(logged_in.get(plan_url(published_quiz())))
    assert '<details class="setting-group"' in html
    assert '<details class="setting-group" id="group-scoreboard" open' not in html
    assert " open>" not in html.split('class="setting-group"', 1)[1].split("</form>")[0]


def test_time_fields_come_before_the_groups(logged_in):
    html = text(logged_in.get(plan_url(published_quiz())))
    first_group = html.index('class="setting-group"')
    for name in ("starts_at", "deadline_at", "limit_minutes"):
        assert html.index(f'name="{name}"') < first_group
    assert "The run takes the quiz's settings." in html


def test_refused_values_open_their_groups(logged_in):
    quiz = published_quiz()
    response = logged_in.post(
        plan_url(quiz),
        {
            "starts_at": START,
            "deadline_at": "",
            "limit_minutes": "",
            "scoreboard_visibility": "live",
            "data_profile": "none",
        },
    )
    html = text(response)
    assert not quiz.runs.exists()
    assert re.search(r'<details class="setting-group" id="group-data" open', html)
    assert re.search(r'<details class="setting-group" id="group-scoreboard" open', html)


def test_a_planned_run_that_differs_opens_its_group(logged_in):
    run = a_plan()
    run.retention_json = {"profile": "detailed", "period": "90d"}
    run.save()
    html = text(logged_in.get(f"/admin/runs/{run.id}/plan?lang=en"))
    assert re.search(r'<details class="setting-group" id="group-data" open', html)
    assert not re.search(r'id="group-participants" open', html)


def test_basic_plan_keeps_a_hidden_run_value(logged_in):
    """A field "Basic" leaves out is not sent; the run then takes the quiz's value."""
    quiz = published_quiz()
    settings.set_override(ASK_EMAIL, quiz, "optional", admin_id=ADMIN_ID)
    logged_in.post(plan_url(quiz), {"starts_at": START, "deadline_at": "", "limit_minutes": ""})
    assert participants.rules_of(quiz.runs.get())[ASK_EMAIL] == "optional"


def test_refused_inherited_value_is_shown_in_basic(logged_in):
    """Review Focus 2: a refusal naming a hidden setting shows it and opens its group."""
    quiz = published_quiz()
    settings.set_override(ASK_EMAIL, quiz, "optional", admin_id=ADMIN_ID)
    response = logged_in.post(
        plan_url(quiz),
        {"starts_at": START, "deadline_at": "", "limit_minutes": "", "data_profile": "none"},
    )
    html = text(response)
    assert not quiz.runs.exists()
    assert re.search(r'<details class="setting-group" id="group-participants" open', html)
    assert 'name="ask_email"' in html


def test_plan_form_edits_the_test_add_on_settings(showing_all):
    logged_in = showing_all
    quiz = published_quiz()
    html = text(logged_in.get(plan_url(quiz)))
    assert 'name="pass_mark"' in html
    assert 'name="max_attempts"' in html
    assert 'name="after_pass"' in html
    logged_in.post(
        plan_url(quiz),
        {
            "starts_at": START,
            "deadline_at": "",
            "limit_minutes": "",
            "pass_mark": "60",
            "max_attempts": "3",
            "after_pass": "stop",
            "official_attempt": "average",
        },
    )
    run = quiz.runs.get()
    assert run.results_json["pass_mark"] == "60"
    assert run.results_json["official_attempt"] == "average"
    assert run.participant_rules_json["max_attempts"] == "3"
    assert run.participant_rules_json["after_pass"] == "stop"


def test_plan_form_refuses_a_pass_mark_over_100(logged_in):
    quiz = published_quiz()
    response = logged_in.post(
        plan_url(quiz),
        {"starts_at": START, "deadline_at": "", "limit_minutes": "", "pass_mark": "101"},
    )
    assert response.status_code == 400
    assert not quiz.runs.exists()


def test_a_refused_plan_says_why_in_an_alert_above_the_form(logged_in):
    """The message was a plain line between paragraphs and went unnoticed."""
    quiz = published_quiz()
    response = logged_in.post(plan_url(quiz), {"starts_at": "2030-01-01T09:00"})
    alert = re.search(
        r'<div class="notice form-errors" role="alert">(.*?)</div>', text(response), re.S
    )
    assert alert is not None and "already passed" in alert.group(1)


def test_every_form_shows_its_own_errors_through_the_alert_macro():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app"
    raw = [
        str(path.relative_to(root))
        for path in root.rglob("*.html")
        if "non_field_errors()" in path.read_text() and path.name != "_form_errors.html"
    ]
    assert raw == []


def test_an_unpublished_quiz_offers_publication_before_the_plan(logged_in):
    """AC-180: a plan needs a published revision; the page says so instead of a dead form."""
    quiz = make_quiz()
    add_question(quiz)
    edit = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert f"/admin/quizzes/{quiz.id}/publish?then=plan" in edit
    page = logged_in.get(plan_url(quiz))
    html = text(page)
    assert page.status_code == 200
    assert 'name="starts_at"' not in html
    assert re.search(r'role="alert"[^>]*>.*Publish the quiz first', html, re.S)
    assert f"/admin/quizzes/{quiz.id}/publish?then=plan" in html
    assert logged_in.post(plan_url(quiz), {"starts_at": START}).status_code == 409
    assert not quiz.runs.exists()


def test_publishing_on_the_way_to_a_plan_goes_on_to_the_plan(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    url = f"/admin/quizzes/{quiz.id}/publish?then=plan"
    found = re.search(r'name="snapshot_hash" value="([^"]*)"', text(logged_in.get(url))).group(1)
    response = logged_in.post(url, {"snapshot_hash": found})
    assert response.status_code == 302
    assert response["Location"] == f"/admin/quizzes/{quiz.id}/plan"
    assert authoring.latest_published(quiz) is not None

"""AC-90, AC-93: reward rules and entitlements in the administration.

The quiz has a template of rules on its tab "Rewards"; a run gets its own copy when it is planned
or opened, and the admin edits that copy on the run's rewards page. The structure of a rule
changes only while the run is planned, its texts at any time. Entitlements are handed over or
cancelled with a reason, manual rewards are granted by hand, and conflicts are shown as messages.
"""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import ASK_EMAIL, REWARD_SOURCE, REWARD_THRESHOLDS, WINNER_CONTACT
from app.domain import (
    attempts,
    authoring,
    participants,
    rewards,
    run_flow,
    run_schedule,
    settings,
)
from app.domain.models import Attempt, Quiz, QuizRun, RewardEntitlement, RewardRule
from tests.domain.helpers import ADMIN_ID, OPTION_A, keep, published_quiz
from tests.support.client import FormClient
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
START = "2030-01-01T18:00"
CONTACT_WARNING = "This run has a draw but does not collect e-mail."
CONTACT_REFUSAL = "A draw needs a required e-mail under the chosen contact setting."


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def text(response):
    return response.content.decode()


def rule_data(kind="threshold", name="Odznak", **fields):
    if kind == "threshold":
        fields.setdefault("threshold_unit", "percent")
        fields.setdefault("threshold_value", Decimal("80"))
    if kind == "draw":
        fields.setdefault("winners", 1)
    return rewards.RuleData(
        kind=kind, texts={"cs": {"name": name, "description": "", "claim": ""}}, **fields
    )


def with_template(*rules, slug="kviz"):
    quiz = published_quiz(slug)
    for data in rules:
        rewards.save_rule(quiz, data, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    return quiz


def a_plan(quiz, **kwargs):
    return run_schedule.plan(
        quiz,
        starts_at=NOW + timedelta(hours=1),
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        **kwargs,
    )


def play(run, key, *, name="", email=None):
    """One browser submits a correct attempt."""
    who = participants.find_or_create(run, key)
    if name or email:
        who.display_name, who.email = name, email
        who.save()
    started = attempts.start(run, participant=who)
    answers = {
        question["id"]: {"options": [OPTION_A]}
        for question in attempts.questions_of(started.attempt)
    }
    attempts.submit(started.attempt.id, started.token, answers, f"key-{key[:8]}")
    assert Attempt.objects.get(pk=started.attempt.id).status == Attempt.Status.SUBMITTED
    return who


def test_quiz_template_rule_created_and_listed(logged_in):
    quiz = published_quiz()
    page = f"/admin/quizzes/{quiz.id}/rewards?lang=en"
    html = text(logged_in.get(page))
    assert "Rewards" in html and f"/admin/quizzes/{quiz.id}/rewards" in html
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/rewards/new?lang=en",
        {
            "kind": "threshold",
            "threshold_unit": "percent",
            "threshold_value": "80",
            "name_cs": "Odznak <b>",
            "description_cs": "Za 80 %",
            "claim_cs": "U pultu",
        },
    )
    assert response.status_code == 302
    (rule,) = rewards.template_of(quiz)
    assert (rule.kind, rule.threshold_unit, rule.threshold_value) == ("threshold", "percent", 80)
    assert rule.texts_json["cs"]["claim"] == "U pultu"
    html = text(logged_in.get(page))
    assert "Odznak &lt;b&gt;" in html and "Odznak <b>" not in html
    # The name is required in the default language; a percent stays at most 100.
    refused = logged_in.post(
        f"/admin/quizzes/{quiz.id}/rewards/new?lang=en",
        {"kind": "threshold", "threshold_unit": "percent", "threshold_value": "120"},
    )
    assert refused.status_code == 400
    assert "This field is required." in text(refused)
    assert len(rewards.template_of(quiz)) == 1
    over = logged_in.post(
        f"/admin/quizzes/{quiz.id}/rewards/new?lang=en",
        {
            "kind": "threshold",
            "threshold_unit": "percent",
            "threshold_value": "120",
            "name_cs": "X",
        },
    )
    assert over.status_code == 400 and "100" in text(over)
    # Changing and deleting by POST; a stale form for a deleted rule gets 404.
    changed = logged_in.post(
        f"/admin/rewards/{rule.id}?lang=en",
        {
            "kind": "threshold",
            "threshold_unit": "points",
            "threshold_value": "3",
            "name_cs": "Nový",
        },
    )
    assert changed.status_code == 302
    rule.refresh_from_db()
    assert (rule.threshold_unit, rule.texts_json["cs"]["name"]) == ("points", "Nový")
    assert logged_in.get(f"/admin/rewards/{rule.id}").status_code == 405
    assert logged_in.post(f"/admin/rewards/{rule.id}", {"action": "delete"}).status_code == 302
    assert rewards.template_of(quiz) == []
    stale = logged_in.post(
        f"/admin/rewards/{rule.id}",
        {"kind": "threshold", "threshold_unit": "points", "threshold_value": "3", "name_cs": "X"},
    )
    assert stale.status_code == 404
    assert logged_in.post(f"/admin/rewards/{rule.id}", {"action": "delete"}).status_code == 404


def test_plan_copies_template_and_shows_rules(logged_in):
    quiz = with_template(rule_data(name="Odznak"))
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/plan?lang=en", {"starts_at": START})
    assert response.status_code == 302
    run = quiz.runs.get()
    assert [rule.texts_json["cs"]["name"] for rule in rewards.rules_of(run)] == ["Odznak"]
    html = text(logged_in.get(f"/admin/runs/{run.id}/plan?lang=en"))
    assert "Odznak" in html
    assert f"/admin/runs/{run.id}/rewards" in html
    run_page = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert f"/admin/runs/{run.id}/rewards" in run_page
    # On a planned run, a rule can be added and changed in full.
    added = logged_in.post(
        f"/admin/runs/{run.id}/rewards/new?lang=en",
        {"kind": "draw", "winners": "2", "alternates": "1", "name_cs": "Losování"},
    )
    assert added.status_code == 302
    draw = rewards.rules_of(run)[1]
    assert (draw.kind, draw.winners, draw.alternates) == ("draw", 2, 1)
    html = text(logged_in.get(f"/admin/runs/{run.id}/rewards?lang=en"))
    assert "Odznak" in html and "Losování" in html
    # The template's own rules stay as they were.
    assert len(rewards.template_of(quiz)) == 1


def test_structure_fields_disabled_on_open_run_texts_saved(logged_in):
    quiz = with_template(rule_data(name="Odznak"))
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    (rule,) = rewards.rules_of(run)
    html = text(logged_in.get(f"/admin/runs/{run.id}/rewards?lang=en"))
    form = html[html.index(f"/admin/rewards/{rule.id}") :]
    kind_select = form[form.index('name="kind"') - 200 : form.index('name="kind"') + 200]
    assert "disabled" in kind_select
    # Posted structure is ignored; the texts are saved.
    response = logged_in.post(
        f"/admin/rewards/{rule.id}?lang=en",
        {
            "kind": "draw",
            "threshold_unit": "points",
            "threshold_value": "1",
            "winners": "5",
            "name_cs": "Nový název",
            "claim_cs": "U pokladny",
        },
    )
    assert response.status_code == 302
    rule.refresh_from_db()
    assert (rule.kind, rule.threshold_unit, rule.threshold_value) == ("threshold", "percent", 80)
    assert rule.texts_json["cs"] == {"name": "Nový název", "description": "", "claim": "U pokladny"}
    # A new rule or a deletion would change the structure: refused with a message, not a 500.
    assert "rewards/new" not in html
    added = logged_in.post(
        f"/admin/runs/{run.id}/rewards/new?lang=en", {"kind": "participation", "name_cs": "Účast"}
    )
    assert added.status_code == 409
    assert "only while the run is planned" in text(added)
    deleted = logged_in.post(f"/admin/rewards/{rule.id}?lang=en", {"action": "delete"})
    assert deleted.status_code == 409
    assert len(rewards.rules_of(run)) == 1


def test_plan_form_sets_threshold_mode_and_contact(showing_all):
    quiz = published_quiz()
    response = showing_all.post(
        f"/admin/quizzes/{quiz.id}/plan?lang=en",
        {"starts_at": START, REWARD_THRESHOLDS: "all", WINNER_CONTACT: "silent"},
    )
    assert response.status_code == 302
    run = quiz.runs.get()
    assert rewards.of(run) == {REWARD_THRESHOLDS: "all", WINNER_CONTACT: "silent"}
    html = text(showing_all.get(f"/admin/runs/{run.id}/plan?lang=en"))
    assert re.search(
        rf'<input type="radio" name="{REWARD_THRESHOLDS}" value="all"[^>]*checked', html
    )
    # A field left out keeps the run's value instead of taking the quiz's.
    showing_all.post(
        f"/admin/runs/{run.id}/plan?lang=en", {"starts_at": START, WINNER_CONTACT: "warn"}
    )
    run.refresh_from_db()
    assert rewards.of(run) == {REWARD_THRESHOLDS: "all", WINNER_CONTACT: "warn"}


def test_conflict_messages_shown_on_plan(logged_in):
    quiz = with_template(rule_data("draw", name="Cena"))
    settings.set_override(WINNER_CONTACT, quiz, "require_email", admin_id=ADMIN_ID)
    planned = logged_in.post(f"/admin/quizzes/{quiz.id}/plan?lang=en", {"starts_at": START})
    assert planned.status_code == 409
    assert CONTACT_REFUSAL in text(planned)
    opened = logged_in.post(f"/admin/quizzes/{quiz.id}/plan?lang=en", {"starts_at": ""})
    assert CONTACT_REFUSAL in text(opened)
    one_click = logged_in.post(f"/admin/quizzes/{quiz.id}/runs?lang=en")
    assert one_click.status_code == 200 and CONTACT_REFUSAL in text(one_click)
    assert not QuizRun.objects.exists()
    # A planned run that the change of the plan would break.
    run = a_plan(quiz, rules={ASK_EMAIL: "required"})
    edited = logged_in.post(
        f"/admin/runs/{run.id}/plan?lang=en", {"starts_at": START, ASK_EMAIL: "off"}
    )
    assert edited.status_code == 409 and CONTACT_REFUSAL in text(edited)
    # Start now when the plan kept a reveal that clashes with its rewards.
    keep(run, settings.NAVIGATION_MODE, "step_back")
    keep(run, settings.REVEAL_MOMENT, "after_each")
    started = logged_in.post(f"/admin/runs/{run.id}/plan/start?lang=en")
    assert started.status_code == 409
    assert "Answers after each question cannot go with rewards." in text(started)
    run.refresh_from_db()
    assert run.status == QuizRun.Status.SCHEDULED
    # Adding a draw to a planned run is checked as well.
    other = a_plan(with_template(slug="jiny"), rewards={WINNER_CONTACT: "require_email"})
    added = logged_in.post(
        f"/admin/runs/{other.id}/rewards/new?lang=en",
        {"kind": "draw", "winners": "1", "name_cs": "Cena"},
    )
    assert added.status_code == 409 and CONTACT_REFUSAL in text(added)
    assert rewards.rules_of(other) == []


def test_contact_warning_shown_under_warn_only(logged_in):
    warned = authoring.open_run(with_template(rule_data("draw", name="Cena")), admin_id=ADMIN_ID)
    assert rewards.of(warned)[WINNER_CONTACT] == "warn"
    for address in (f"/admin/runs/{warned.id}?lang=en", f"/admin/runs/{warned.id}/rewards?lang=en"):
        assert CONTACT_WARNING in text(logged_in.get(address))
    silent = authoring.open_run(
        with_template(rule_data("draw", name="Cena"), slug="tichy"),
        admin_id=ADMIN_ID,
        rewards={WINNER_CONTACT: "silent"},
    )
    for address in (f"/admin/runs/{silent.id}?lang=en", f"/admin/runs/{silent.id}/rewards?lang=en"):
        assert CONTACT_WARNING not in text(logged_in.get(address))
    collected = authoring.open_run(
        with_template(rule_data("draw", name="Cena"), slug="sbira"),
        admin_id=ADMIN_ID,
        rules={ASK_EMAIL: "optional"},
    )
    assert CONTACT_WARNING not in text(logged_in.get(f"/admin/runs/{collected.id}/rewards?lang=en"))
    no_draw = authoring.open_run(with_template(rule_data(), slug="prah"), admin_id=ADMIN_ID)
    assert CONTACT_WARNING not in text(logged_in.get(f"/admin/runs/{no_draw.id}/rewards?lang=en"))


def test_hand_over_and_cancel_need_post_and_reason(logged_in):
    run = authoring.open_run(
        with_template(rule_data("participation", name="Účast")),
        admin_id=ADMIN_ID,
        rules={ASK_EMAIL: "optional"},
    )
    play(run, "a" * 20, name="Alena", email="alena@example.org")
    play(run, "b" * 20)
    first, second = RewardEntitlement.objects.order_by("created_at", "id")
    html = text(logged_in.get(f"/admin/runs/{run.id}/rewards?lang=en"))
    assert "Alena" in html and "alena@example.org" in html
    assert "Player 2" in html  # no name: the anonymous label
    address = f"/admin/entitlements/{first.id}?lang=en"
    assert logged_in.get(address).status_code == 405
    refused = logged_in.post(address, {"action": "cancel", "reason": "  "})
    assert refused.status_code == 400 and "Enter a reason" in text(refused)
    first.refresh_from_db()
    assert first.status == "granted"
    assert logged_in.post(address, {"action": "hand_over"}).status_code == 302
    first.refresh_from_db()
    assert first.status == "handed_over"
    again = logged_in.post(address, {"action": "hand_over"})
    assert again.status_code == 409
    assert logged_in.post(address, {"action": "cancel", "reason": "Vrátil"}).status_code == 302
    first.refresh_from_db()
    assert (first.status, first.reason) == ("cancelled", "Vrátil")
    assert logged_in.post(address, {"action": "bogus"}).status_code == 400
    second.refresh_from_db()
    assert second.status == "granted"
    html = text(logged_in.get(f"/admin/runs/{run.id}/rewards?lang=en"))
    assert "Cancelled" in html and "Vrátil" in html
    assert logged_in.post(
        "/admin/entitlements/0190a0a0-0000-7000-8000-000000000000"
    ).status_code == (404)


def test_manual_grant(logged_in):
    run = authoring.open_run(with_template(rule_data("manual", name="Porota")), admin_id=ADMIN_ID)
    (rule,) = rewards.rules_of(run)
    who = play(run, "a" * 20, name="Alena")
    participants.find_or_create(run, "c" * 20)  # no submitted attempt: not offered
    html = text(logged_in.get(f"/admin/runs/{run.id}/rewards?lang=en"))
    grant_form = html[html.index(f"/admin/runs/{run.id}/rewards/grant") :]
    assert grant_form.count('name="participant"') == 1 and grant_form.count("<option") == 2
    response = logged_in.post(
        f"/admin/runs/{run.id}/rewards/grant?lang=en",
        {"rule": str(rule.id), "participant": str(who.id)},
    )
    assert response.status_code == 302
    row = RewardEntitlement.objects.get()
    assert (row.participant_id, row.source, row.status) == (who.id, "manual", "granted")
    for wrong in (
        {"rule": "nonsense", "participant": str(who.id)},
        {"rule": str(rule.id), "participant": "nonsense"},
        {"rule": str(rule.id)},
    ):
        response = logged_in.post(f"/admin/runs/{run.id}/rewards/grant", wrong)
        assert response.status_code == 404
    other = authoring.open_run(with_template(rule_data("manual"), slug="jiny"), admin_id=ADMIN_ID)
    stranger = play(other, "d" * 20)
    response = logged_in.post(
        f"/admin/runs/{run.id}/rewards/grant",
        {"rule": str(rule.id), "participant": str(stranger.id)},
    )
    assert response.status_code == 404
    assert RewardEntitlement.objects.count() == 1


def test_pages_need_login(logged_in):
    quiz = with_template(rule_data())
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    (rule,) = rewards.rules_of(run)
    anonymous = FormClient()
    for address in (f"/admin/quizzes/{quiz.id}/rewards", f"/admin/runs/{run.id}/rewards"):
        response = anonymous.get(address)
        assert response.status_code == 302 and "/admin/login" in response["Location"]
    for address in (
        f"/admin/rewards/{rule.id}",
        f"/admin/quizzes/{quiz.id}/rewards/new",
        f"/admin/runs/{run.id}/rewards/new",
        f"/admin/runs/{run.id}/rewards/grant",
        f"/admin/entitlements/{rule.id}",
    ):
        response = anonymous.post(address, {"action": "delete", "name_cs": "X"})
        assert response.status_code == 302
    assert RewardRule.objects.count() == 2


def test_advanced_fields_shown_with_showing_all(showing_all):
    quiz = published_quiz()
    html = text(showing_all.get(f"/admin/quizzes/{quiz.id}/plan?lang=en"))
    assert f'name="{REWARD_THRESHOLDS}"' in html and f'name="{WINNER_CONTACT}"' in html
    rewards_group = html.split('id="group-rewards"')[1].split("</details>")[0]  # AC-168
    assert f'name="{REWARD_THRESHOLDS}"' in rewards_group
    showing_all.cookies["kvz_admin_view"] = "basic"
    basic = text(showing_all.get(f"/admin/quizzes/{quiz.id}/plan?lang=en"))
    assert f'name="{REWARD_THRESHOLDS}"' not in basic


def test_refused_start_now_still_shows_the_rewards(logged_in):
    quiz = with_template(rule_data("draw", name="Cena"))
    run = a_plan(quiz)
    keep(run, settings.NAVIGATION_MODE, "step_back")
    keep(run, settings.REVEAL_MOMENT, "after_each")
    refused = logged_in.post(f"/admin/runs/{run.id}/plan/start?lang=en")
    assert refused.status_code == 409
    html = text(refused)
    assert "Answers after each question cannot go with rewards." in html
    assert "Cena" in html and "No rewards." not in html
    assert CONTACT_WARNING in html


def test_archived_quiz_template_offers_no_save(logged_in):
    quiz = with_template(rule_data(name="Odznak"))
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/rewards?lang=en"))
    assert "Save the reward" in html
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/rewards?lang=en"))
    assert "Odznak" in html and "Save the reward" not in html


def test_after_each_on_a_quiz_with_a_planned_run_with_rules_asks_and_offers_only_next(logged_in):
    """AC-18: a planned run with rewards cannot take answers after each question: next run only."""
    quiz = with_template(rule_data())
    a_plan(quiz)
    asked = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings?lang=en",
        {
            "slug": quiz.slug,
            settings.NAVIGATION_MODE: "step_back",
            settings.REVEAL_MOMENT: "after_each",
        },
    )
    assert asked.status_code == 200
    assert "Answers after each question cannot go with rewards." in text(asked)
    assert 'value="run"' not in text(asked)
    assert settings.quiz_override(settings.REVEAL_MOMENT, quiz) is None


def test_global_reveal_after_each_is_saved_and_a_live_run_with_rules_keeps_its_value(logged_in):
    """AC-18: a global change never changes a planned or open run, so it is not refused."""
    quiz = with_template(rule_data())
    run = a_plan(quiz)
    kept = run_flow.of(run)
    saved = logged_in.post("/admin/settings?lang=en", {settings.REVEAL_MOMENT: "after_each"})
    assert saved.status_code == 302
    assert settings.resolve(settings.REVEAL_MOMENT) == "after_each"
    run.refresh_from_db()
    assert run_flow.of(run) == kept


def test_global_reveal_after_each_is_allowed_without_runs_with_rules(logged_in):
    a_plan(published_quiz("bez"))
    allowed = logged_in.post(
        "/admin/settings",
        {settings.REVEAL_MOMENT: "after_each", settings.NAVIGATION_MODE: "step_back"},
    )
    assert allowed.status_code == 302


def test_add_a_reward_looks_like_a_button(logged_in):
    """A bare summary reads as plain text; the editors' "Add question" is a button too."""
    quiz = published_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/rewards?lang=en"))
    assert '<summary role="button">Add a reward</summary>' in html


ARCHIVED = "This quiz is archived. Restore it to change it."


def archived_run(*rules):
    """A closed run of an archived quiz: only a closed run lets a quiz be archived."""
    run = authoring.open_run(with_template(*rules), admin_id=ADMIN_ID)
    return run


def archive(run):
    authoring.close_run(run, admin_id=ADMIN_ID)
    Quiz.objects.filter(pk=run.quiz_id).update(archived_at=NOW)


def test_entitlement_change_on_an_archived_quiz_answers_409(logged_in):
    run = archived_run(rule_data("participation", name="Účast"))
    play(run, "a" * 20)
    row = RewardEntitlement.objects.get()
    archive(run)
    address = f"/admin/entitlements/{row.id}?lang=en"
    for data in ({"action": "hand_over"}, {"action": "cancel", "reason": "Vrátil"}):
        response = logged_in.post(address, data)
        assert response.status_code == 409 and ARCHIVED in text(response)
    row.refresh_from_db()
    assert row.status == "granted"
    assert logged_in.get(f"/admin/runs/{run.id}/rewards?lang=en").status_code == 200


def test_manual_grant_on_an_archived_quiz_answers_409(logged_in):
    run = archived_run(rule_data("manual", name="Ručně"))
    who = play(run, "a" * 20)
    rule = RewardRule.objects.get(run=run, kind="manual")
    archive(run)
    response = logged_in.post(
        f"/admin/runs/{run.id}/rewards/grant?lang=en",
        {"rule": str(rule.id), "participant": str(who.id)},
    )
    assert response.status_code == 409 and ARCHIVED in text(response)
    assert not RewardEntitlement.objects.exists()


def test_draw_on_an_archived_quiz_answers_409(logged_in):
    run = archived_run(rule_data("draw", name="Cena"))
    play(run, "a" * 20)
    rule = RewardRule.objects.get(run=run, kind="draw")
    archive(run)
    response = logged_in.post(f"/admin/runs/{run.id}/draw/{rule.id}?lang=en", {"action": "draw"})
    assert response.status_code == 409 and ARCHIVED in text(response)
    assert logged_in.get(f"/admin/runs/{run.id}/draw?lang=en").status_code == 200


def test_run_changes_on_an_archived_quiz_answer_409(logged_in):
    run = archived_run(rule_data("participation", name="Účast"))
    who = play(run, "a" * 20)
    archive(run)
    for address, data in (
        (f"/admin/runs/{run.id}/scoreboard/settings?lang=en", {"scoreboard_visibility": "during"}),
        (f"/admin/runs/{run.id}/code?lang=en", {"action": "generate"}),
        (f"/admin/runs/{run.id}/participants/{who.id}/name?lang=en", {"name": "Nové"}),
    ):
        response = logged_in.post(address, data)
        assert response.status_code == 409 and ARCHIVED in text(response)
    run.refresh_from_db()
    assert run.access_code_hash == ""
    assert logged_in.get(f"/admin/runs/{run.id}?lang=en").status_code == 200

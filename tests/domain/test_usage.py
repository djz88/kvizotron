import pytest

from app.domain import authoring, usage
from app.domain.models import QuizRevision
from app.kernel import lifecycle
from tests.domain.helpers import ADMIN_ID, open_quiz_run

pytestmark = pytest.mark.django_db


def set_enabled(module, value):
    lifecycle.set_enabled(module, value, actor_type="admin", actor_id=ADMIN_ID)


@pytest.mark.parametrize("module", ["question.choice", "scoring.basic"])
def test_plugin_used_by_open_run_cannot_be_disabled(module):
    open_quiz_run()
    with pytest.raises(lifecycle.ModuleInUse, match="kviz"):
        set_enabled(module, False)


def test_question_plugin_can_be_disabled_after_run_closes():
    authoring.close_run(open_quiz_run(), admin_id=ADMIN_ID)
    set_enabled("question.choice", False)
    set_enabled("question.choice", True)


def test_no_startup_problem_when_open_run_has_its_plugins():
    open_quiz_run()
    assert usage.missing_plugin_problems() == []


def test_startup_problem_when_open_run_needs_uninstalled_type():
    run = open_quiz_run()
    snapshot = run.current_revision.snapshot_json
    snapshot["questions"][0]["type"] = "gone.type"
    QuizRevision.objects.filter(pk=run.current_revision_id).update(snapshot_json=snapshot)
    problems = usage.missing_plugin_problems()
    assert len(problems) == 1
    assert "gone.type" in problems[0] and "kviz" in problems[0]


# Reward and drawing modules (C5, ADR-0053): the grant and the draw call them.


def run_with_rule(kind="threshold", **data):
    from decimal import Decimal

    from app.contracts import REWARD_SOURCE
    from app.domain import rewards, settings
    from tests.domain.helpers import published_quiz

    quiz = published_quiz()
    fields = (
        {"threshold_unit": "percent", "threshold_value": Decimal(50)}
        if kind == "threshold"
        else {"winners": 1, "alternates": 0}
        if kind == "draw"
        else {}
    )
    rule = rewards.RuleData(
        kind=kind, texts={"cs": {"name": "Cena", "description": "", "claim": ""}}, **fields | data
    )
    rewards.save_rule(quiz, rule, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    return quiz


def test_threshold_plugin_cannot_be_disabled_while_a_run_has_threshold_rules():
    quiz = run_with_rule("threshold")
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    with pytest.raises(lifecycle.ModuleInUse, match="run 1 of quiz kviz"):
        set_enabled("rewards.threshold", False)


def test_threshold_plugin_can_be_disabled_without_threshold_rules():
    quiz = run_with_rule("participation")
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    set_enabled("rewards.threshold", False)
    set_enabled("rewards.threshold", True)


def test_drawing_plugin_cannot_be_disabled_while_a_run_has_a_draw_rule():
    quiz = run_with_rule("draw")
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    with pytest.raises(lifecycle.ModuleInUse, match="run 1 of quiz kviz"):
        set_enabled("drawings.manual", False)


def test_drawing_plugin_can_be_disabled_with_only_threshold_rules():
    authoring.open_run(run_with_rule("threshold"), admin_id=ADMIN_ID)
    set_enabled("drawings.manual", False)
    set_enabled("drawings.manual", True)


def test_threshold_plugin_is_needed_by_the_minimum_of_a_draw():
    from decimal import Decimal

    quiz = run_with_rule("draw", min_unit="percent", min_value=Decimal(50))
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    with pytest.raises(lifecycle.ModuleInUse):
        set_enabled("rewards.threshold", False)


def test_reward_modules_can_be_disabled_once_the_run_is_archived():
    quiz = run_with_rule("threshold")
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    authoring.close_run(run, admin_id=ADMIN_ID)
    with pytest.raises(lifecycle.ModuleInUse):
        set_enabled("rewards.threshold", False)
    from app.domain import run_schedule

    run_schedule.archive(run, admin_id=ADMIN_ID)
    set_enabled("rewards.threshold", False)
    set_enabled("rewards.threshold", True)

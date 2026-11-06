import pytest

from app.domain import authoring, usage
from app.domain.models import QuizRevision
from app.kernel import lifecycle
from tests.domain.helpers import ADMIN_ID, open_quiz_run

pytestmark = pytest.mark.django_db


def set_enabled(module, value):
    lifecycle.set_enabled(module, value, actor_type="admin", actor_id=ADMIN_ID)


@pytest.mark.parametrize("module", ["question.choice_single", "scoring.basic"])
def test_plugin_used_by_open_run_cannot_be_disabled(module):
    open_quiz_run()
    with pytest.raises(lifecycle.ModuleInUse, match="kviz"):
        set_enabled(module, False)


def test_question_plugin_can_be_disabled_after_run_closes():
    authoring.close_run(open_quiz_run(), admin_id=ADMIN_ID)
    set_enabled("question.choice_single", False)
    set_enabled("question.choice_single", True)


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

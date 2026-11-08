"""AC-77: the upgrade turns `store_answers` into a data profile and fills the runs."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = [("domain", "0012_participants")]
AFTER = [("domain", "0013_data_policies")]


@pytest.fixture(autouse=True)
def back_to_latest():
    """The next transactional test needs every migration, not the one this file stops at."""
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def test_migration_maps_store_answers():
    old = migrate(BEFORE)
    quiz_model, setting, run_model, revision_model = (
        old.get_model("domain", name) for name in ("Quiz", "AppSetting", "QuizRun", "QuizRevision")
    )
    quiz = quiz_model.objects.create(
        slug="kviz", title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    other = quiz_model.objects.create(
        slug="jiny", title={"cs": "J"}, default_locale="cs", supported_locales=["cs"]
    )

    def revision_for(owner):
        return revision_model.objects.create(
            quiz=owner,
            revision_no=1,
            status="PUBLISHED",
            snapshot_json={},
            max_score=0,
        )

    setting.objects.create(key="store_answers", value_json="all")
    setting.objects.create(key="store_answers", value_json="images", quiz=quiz)
    mine = run_model.objects.create(quiz=quiz, run_no=1, current_revision=revision_for(quiz))
    theirs = run_model.objects.create(quiz=other, run_no=1, current_revision=revision_for(other))

    new = migrate(AFTER)
    setting, run_model = (new.get_model("domain", name) for name in ("AppSetting", "QuizRun"))
    assert not setting.objects.filter(key="store_answers").exists()
    assert setting.objects.get(key="data_profile", quiz=None).value_json == "answers"
    assert setting.objects.get(key="data_profile", quiz_id=quiz.id).value_json == "score"
    assert run_model.objects.get(pk=mine.pk).retention_json == {"profile": "score", "period": "90d"}
    assert run_model.objects.get(pk=theirs.pk).retention_json == {
        "profile": "answers",
        "period": "90d",
    }
    assert run_model.objects.get(pk=mine.pk).stateless_submitted == 0


def _quiz_and_revision(old):
    quiz = old.get_model("domain", "Quiz").objects.create(
        slug="kviz", title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    revision = old.get_model("domain", "QuizRevision").objects.create(
        quiz=quiz, revision_no=1, status="PUBLISHED", snapshot_json={}, max_score=0
    )
    return quiz, revision


def test_migration_fills_scheduled_ended_and_test_runs():
    old = migrate(BEFORE)
    quiz, revision = _quiz_and_revision(old)
    run_model = old.get_model("domain", "QuizRun")
    scheduled = run_model.objects.create(
        quiz=quiz, run_no=1, current_revision=revision, status="SCHEDULED"
    )
    ended = run_model.objects.create(
        quiz=quiz, run_no=2, current_revision=revision, status="CLOSED"
    )
    test = run_model.objects.create(quiz=quiz, run_no=None, current_revision=revision, kind="test")

    new = migrate(AFTER)
    run_model = new.get_model("domain", "QuizRun")
    for run in (scheduled, ended):
        assert run_model.objects.get(pk=run.pk).retention_json == {
            "profile": "score",
            "period": "90d",
        }
    assert run_model.objects.get(pk=test.pk).retention_json == {}


def test_migration_reverse_maps_profiles_back():
    old = migrate(BEFORE)
    quiz, _revision = _quiz_and_revision(old)
    setting = old.get_model("domain", "AppSetting")
    setting.objects.create(key="store_answers", value_json="all")
    setting.objects.create(key="store_answers", value_json="images", quiz=quiz)
    migrate(AFTER)
    setting = migrate(AFTER).get_model("domain", "AppSetting")
    other = setting.objects.get(key="data_profile", quiz_id=quiz.id)
    other.value_json = "detailed"
    other.save()

    back = migrate(BEFORE)
    setting = back.get_model("domain", "AppSetting")
    assert not setting.objects.filter(key="data_profile").exists()
    assert setting.objects.get(key="store_answers", quiz=None).value_json == "all"
    assert setting.objects.get(key="store_answers", quiz_id=quiz.id).value_json == "all"
    migrate(AFTER)

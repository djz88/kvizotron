"""AC-185: the upgrade gives every normal run the values its quiz reads today (ADR-0069)."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = [("domain", "0027_quiz_public_origin")]
AFTER = [("domain", "0028_run_flow")]


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


def test_runs_get_the_values_their_quiz_reads_today():
    old = migrate(BEFORE)
    quiz = old.get_model("domain", "Quiz").objects.create(
        slug="a", title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    revision = old.get_model("domain", "QuizRevision").objects.create(quiz=quiz, revision_no=1)
    runs = old.get_model("domain", "QuizRun")._base_manager
    normal = runs.create(quiz=quiz, current_revision=revision, run_no=1, status="OPEN")
    test = runs.create(quiz=quiz, current_revision=revision, kind="test", status="OPEN")
    setting = old.get_model("domain", "AppSetting").objects
    setting.create(key="reveal_moment", quiz=quiz, value_json="never")
    setting.create(key="navigation_mode", quiz=None, value_json="pages")
    setting.create(key="page_size", quiz=quiz, value_json="999")

    new = migrate(AFTER).get_model("domain", "QuizRun")._base_manager

    kept = new.get(pk=normal.pk).flow_json
    assert kept["reveal_moment"] == "never"
    assert kept["navigation_mode"] == "pages"
    assert kept["page_size"] == "5"
    assert set(kept) == {
        "navigation_mode",
        "page_size",
        "reveal_moment",
        "reveal_level",
        "shuffle_questions",
        "shuffle_options",
        "show_sources",
    }
    assert new.get(pk=test.pk).flow_json == {}

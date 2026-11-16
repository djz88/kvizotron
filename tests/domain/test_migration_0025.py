"""AC-06: the upgrade shows existing runs in one table by percent (ADR-0065)."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = [("domain", "0024_participant_number")]
AFTER = [("domain", "0025_revision_mode_percent")]


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


def old_run(old, slug, results_json, kind="normal"):
    quiz = old.get_model("domain", "Quiz").objects.create(
        slug=slug, title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    revision = old.get_model("domain", "QuizRevision").objects.create(quiz=quiz, revision_no=1)
    return old.get_model("domain", "QuizRun")._base_manager.create(
        quiz=quiz,
        current_revision=revision,
        kind=kind,
        run_no=1,
        status="OPEN",
        results_json=results_json,
    )


def test_migration_switches_separate_and_merged_runs_to_percent():
    old = migrate(BEFORE)
    separate = old_run(old, "a", {"revision_mode": "separate", "seed": "s"})
    merged = old_run(old, "b", {"revision_mode": "separate", "merged": "on"})
    latest = old_run(old, "c", {"revision_mode": "latest"})
    merged_latest = old_run(old, "d", {"revision_mode": "latest", "merged": "on"})
    test = old_run(old, "e", {"revision_mode": "separate", "merged": "on"}, kind="test")

    runs = migrate(AFTER).get_model("domain", "QuizRun")._base_manager

    stored = {run.pk: run.results_json for run in runs.all()}
    assert stored[separate.pk] == {"revision_mode": "percent", "seed": "s"}
    assert stored[merged.pk] == {"revision_mode": "percent"}
    assert stored[latest.pk] == {"revision_mode": "latest"}
    assert stored[merged_latest.pk] == {"revision_mode": "percent"}
    assert stored[test.pk] == {"revision_mode": "separate", "merged": "on"}


def test_going_back_changes_nothing():
    old = migrate(BEFORE)
    run = old_run(old, "a", {"revision_mode": "separate"})
    migrate(AFTER)

    back = migrate(BEFORE).get_model("domain", "QuizRun")._base_manager

    assert back.get(pk=run.pk).results_json == {"revision_mode": "percent"}

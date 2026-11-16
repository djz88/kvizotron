"""The upgrade stores each participant's anonymous number, so a later erasure shifts nothing."""

from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = [("domain", "0023_quiz_type")]
AFTER = [("domain", "0024_participant_number")]
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


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


def old_run(old, slug="kviz"):
    quiz = old.get_model("domain", "Quiz").objects.create(
        slug=slug, title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    revision = old.get_model("domain", "QuizRevision").objects.create(quiz=quiz, revision_no=1)
    return old.get_model("domain", "QuizRun").objects.create(
        quiz=quiz, current_revision=revision, kind="normal", run_no=1, status="OPEN"
    )


def joined(people, run, key, minute):
    row = people.objects.create(run=run, anonymous_key_hash=key)
    people.objects.filter(pk=row.pk).update(created_at=T0 + timedelta(minutes=minute))
    return row


def test_existing_rows_get_numbers_in_creation_order_per_run():
    old = migrate(BEFORE)
    people = old.get_model("domain", "Participant")
    one, two = old_run(old, "a"), old_run(old, "b")
    joined(people, one, "late", 9)
    joined(people, two, "other", 0)
    joined(people, one, "early", 1)
    joined(people, one, "middle", 5)

    model = migrate(AFTER).get_model("domain", "Participant")

    numbers = {row.anonymous_key_hash: row.number for row in model.objects.all()}
    assert numbers == {"early": 1, "middle": 2, "late": 3, "other": 1}


def test_each_run_continues_after_its_highest_number():
    old = migrate(BEFORE)
    people = old.get_model("domain", "Participant")
    one, two, empty = old_run(old, "a"), old_run(old, "b"), old_run(old, "c")
    for minute in range(3):
        joined(people, one, f"h{minute}", minute)
    joined(people, two, "other", 0)

    runs = migrate(AFTER).get_model("domain", "QuizRun")

    seqs = {run.pk: run.participant_seq for run in runs.objects.all()}
    assert seqs == {one.pk: 3, two.pk: 1, empty.pk: 0}


def test_the_same_moment_is_ordered_by_id():
    old = migrate(BEFORE)
    people = old.get_model("domain", "Participant")
    run = old_run(old)
    rows = [joined(people, run, f"h{index}", 0) for index in range(3)]

    model = migrate(AFTER).get_model("domain", "Participant")

    by_id = sorted(rows, key=lambda row: row.pk)
    assert [model.objects.get(pk=row.pk).number for row in by_id] == [1, 2, 3]


def test_going_back_drops_the_column():
    old = migrate(BEFORE)
    run = old_run(old)
    old.get_model("domain", "Participant").objects.create(run=run, anonymous_key_hash="h")
    migrate(AFTER)

    back = migrate(BEFORE)

    assert not any(
        field.name == "number"
        for field in back.get_model("domain", "Participant")._meta.get_fields()
    )
    run_fields = back.get_model("domain", "QuizRun")._meta.get_fields()
    assert not any(field.name == "participant_seq" for field in run_fields)
    assert back.get_model("domain", "Participant").objects.get().anonymous_key_hash == "h"

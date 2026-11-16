"""Stores each participant's anonymous number and each run's counter of them.

Existing rows are numbered as the board derived them; each run's counter starts at its highest.
"""

from django.db import migrations, models
from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce


def fill_numbers(apps, schema_editor):
    """Per run in (created_at, id) order, the order the board used to derive the number from."""
    people = apps.get_model("domain", "Participant")
    run_id = None
    number = 0
    changed = []
    for row in people.objects.order_by("run_id", "created_at", "id").only("id", "run_id"):
        if row.run_id != run_id:
            run_id, number = row.run_id, 0
        number += 1
        row.number = number
        changed.append(row)
        if len(changed) >= 500:
            people.objects.bulk_update(changed, ["number"])
            changed = []
    if changed:
        people.objects.bulk_update(changed, ["number"])
    runs = apps.get_model("domain", "QuizRun")
    highest = people.objects.filter(run=OuterRef("pk")).order_by("-number").values("number")[:1]
    runs._base_manager.update(participant_seq=Coalesce(Subquery(highest), 0))


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0023_quiz_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="quizrun",
            name="participant_seq",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="participant",
            name="number",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(fill_numbers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="participant",
            constraint=models.UniqueConstraint(
                fields=("run", "number"), name="participant_number_per_run"
            ),
        ),
    ]

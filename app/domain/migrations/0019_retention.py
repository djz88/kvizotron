"""D3: what a run keeps after deletion, and a hold on runs already past their period."""

from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone

# A migration keeps its own copy: it must mean this even if the settings change later.
PERIOD_DAYS = {"30d": 30, "90d": 90, "180d": 180, "1y": 365, "3y": 1095}
MISSING_PERIOD = "90d"
UNSETTLED = ("OPEN", "SCHEDULED")


def effective_close(run):
    """A run past its deadline stays open until `settle`, which then closes it at the deadline."""
    if run.closed_at is None and run.status in UNSETTLED:
        return run.deadline_at
    return run.closed_at


def hold_due_runs(apps, schema_editor) -> None:
    """Nobody chose deletion for these runs, so the job must not start with them."""
    run_model = apps.get_model("domain", "QuizRun")
    now = timezone.now()
    due = []
    for run in run_model.objects.filter(kind="normal"):
        closed = effective_close(run)
        days = PERIOD_DAYS.get((run.retention_json or {}).get("period", MISSING_PERIOD))
        if closed is not None and days is not None and closed + timedelta(days=days) <= now:
            due.append(run.pk)
    run_model.objects.filter(pk__in=due).update(retention_held_at=now)


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0018_quiz_created_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="quizrun",
            name="data_deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="quizrun",
            name="retention_held_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="quizrun",
            name="retention_summary_json",
            field=models.JSONField(default=dict),
        ),
        migrations.RunPython(hold_due_runs, migrations.RunPython.noop),
    ]

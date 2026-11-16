"""Existing runs show one table by percent (ADR-0065).

A run with one table per revision, or with the old per-run merge switched on, becomes `percent`
and loses the `merged` key; `latest` stays. Test runs follow the quiz and are left alone.
"""

from django.db import migrations

PERCENT = "percent"


def to_percent(apps, schema_editor):
    runs = apps.get_model("domain", "QuizRun")
    changed = []
    for run in runs._base_manager.exclude(kind="test").only("id", "results_json"):
        stored = dict(run.results_json or {})
        merged = stored.pop("merged", None) == "on"
        if merged or stored.get("revision_mode") == "separate":
            stored["revision_mode"] = PERCENT
        if stored != run.results_json:
            run.results_json = stored
            changed.append(run)
    runs._base_manager.bulk_update(changed, ["results_json"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0024_participant_number"),
    ]

    operations = [
        migrations.RunPython(to_percent, migrations.RunPython.noop),
    ]

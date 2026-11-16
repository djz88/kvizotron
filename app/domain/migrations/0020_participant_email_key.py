"""D5 follow-up: the address of a participant, stripped and casefolded, for the erasure search."""

from django.db import migrations, models

BATCH = 500


def fill_keys(apps, schema_editor) -> None:
    """The rule is written here on purpose: a migration must mean this even if the code changes."""
    model = apps.get_model("domain", "Participant")
    rows = model.objects.exclude(email__isnull=True).exclude(email="")
    last = None
    while True:
        batch = rows.order_by("pk")
        if last is not None:
            batch = batch.filter(pk__gt=last)
        found = list(batch.only("pk", "email")[:BATCH])
        if not found:
            return
        for row in found:
            row.email_key = row.email.strip().casefold() or None
        model.objects.bulk_update(found, ["email_key"])
        last = found[-1].pk


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0019_retention"),
    ]

    operations = [
        migrations.AddField(
            model_name="participant",
            name="email_key",
            field=models.CharField(blank=True, db_index=True, max_length=762, null=True),
        ),
        migrations.RunPython(fill_keys, migrations.RunPython.noop),
    ]

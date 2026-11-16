"""A run may show its rows on the public board of a main run (ADR-0065); none does yet."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0025_revision_mode_percent"),
    ]

    operations = [
        migrations.AddField(
            model_name="quizrun",
            name="board_main",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="board_members",
                to="domain.quizrun",
            ),
        ),
    ]

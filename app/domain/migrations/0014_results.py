"""C4: the anonymous label on a quiz and scoreboard settings on a run. Old runs read as hidden."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0013_data_policies"),
    ]

    operations = [
        migrations.AddField(
            model_name="quiz",
            name="anonymous_label",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="quizrun",
            name="results_json",
            field=models.JSONField(default=dict),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0006_four_decimal_places"),
    ]

    operations = [
        migrations.AddField(
            model_name="attempt",
            name="selection_json",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="attempt",
            name="settings_json",
            field=models.JSONField(blank=True, null=True),
        ),
    ]

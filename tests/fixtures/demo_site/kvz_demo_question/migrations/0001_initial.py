import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="DemoAnswer",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("earned_points", models.FloatField()),
            ],
        ),
    ]

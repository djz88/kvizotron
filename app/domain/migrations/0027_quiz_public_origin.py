from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("domain", "0026_run_board_main")]

    operations = [
        migrations.AddField(
            model_name="quiz",
            name="public_origin",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("kernel", "0003_plugininstallation_inactive"),
    ]

    operations = [
        migrations.AddField(
            model_name="adminuser",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
    ]

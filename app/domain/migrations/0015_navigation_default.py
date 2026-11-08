"""C4.5: one question at a time becomes the default, but an existing installation plays as before.

A database that already has an admin or a quiz keeps "all at once" as its stored global value,
so its quizzes, new ones included, do not change (ADR-0052). A fresh one has neither.
"""

from django.db import migrations


def keep_all_at_once(apps, schema_editor):
    setting = apps.get_model("domain", "AppSetting")
    if setting.objects.filter(key="navigation_mode", quiz=None).exists():
        return
    existing = (
        apps.get_model("kernel", "AdminUser").objects.exists()
        or apps.get_model("domain", "Quiz").objects.exists()
    )
    if existing:
        setting.objects.create(key="navigation_mode", value_json="all_at_once")


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0014_results"),
        ("kernel", "0003_plugininstallation_inactive"),
    ]

    operations = [migrations.RunPython(keep_all_at_once, migrations.RunPython.noop)]

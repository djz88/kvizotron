from django.db import migrations, models

# The seven values a run keeps, with their choices and defaults as the catalogue has them today.
# Copied here so the migration stands alone.
ON_OFF = ("on", "off")
FLOW = {
    "navigation_mode": (("all_at_once", "step_back", "step_no_back", "pages"), "step_back"),
    "page_size": (tuple(str(size) for size in range(2, 21)), "5"),
    "reveal_moment": (("never", "at_end", "after_each", "after_close"), "never"),
    "reveal_level": (("verdict", "answers", "explanations"), "verdict"),
    "shuffle_questions": (ON_OFF, "off"),
    "shuffle_options": (ON_OFF, "off"),
    "show_sources": (ON_OFF, "on"),
}


def fill(apps, schema_editor):
    app_setting = apps.get_model("domain", "AppSetting")
    quiz_run = apps.get_model("domain", "QuizRun")
    globals_ = {row.key: row.value_json for row in app_setting.objects.filter(quiz__isnull=True)}
    overrides: dict[tuple, str] = {
        (row.quiz_id, row.key): row.value_json
        for row in app_setting.objects.filter(quiz__isnull=False)
    }
    for run in quiz_run._base_manager.exclude(kind="test"):
        kept = {}
        for key, (choices, default) in FLOW.items():
            for candidate in (overrides.get((run.quiz_id, key)), globals_.get(key)):
                if candidate in choices:
                    kept[key] = candidate
                    break
            else:
                kept[key] = default
        run.flow_json = kept
        run.save(update_fields=["flow_json"])


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0027_quiz_public_origin"),
    ]

    operations = [
        migrations.AddField(
            model_name="quizrun",
            name="flow_json",
            field=models.JSONField(default=dict),
        ),
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]

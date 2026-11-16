from django.db import migrations, models


def fill_created_by(quiz_model, audit_model, admin_model) -> None:
    """Existing quizzes get the admin of their oldest audit event, else the oldest admin."""
    oldest = admin_model.objects.order_by("created_at").values_list("pk", flat=True).first()
    fallback = str(oldest) if oldest is not None else ""
    for quiz in quiz_model.objects.filter(created_by=""):
        actor = (
            audit_model.objects.filter(
                actor_type="admin", entity_id=str(quiz.pk), actor_id__isnull=False
            )
            .order_by("created_at")
            .values_list("actor_id", flat=True)
            .first()
        )
        created_by = actor or fallback
        if created_by:
            quiz_model.objects.filter(pk=quiz.pk).update(created_by=created_by)


def forwards(apps, schema_editor) -> None:
    fill_created_by(
        apps.get_model("domain", "Quiz"),
        apps.get_model("kernel", "AuditEvent"),
        apps.get_model("kernel", "AdminUser"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0017_branding"),
        ("kernel", "0004_adminuser_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="quiz",
            name="created_by",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

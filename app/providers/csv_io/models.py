import uuid

from django.db import models


class ImportJobRecord(models.Model):
    """An upload between its check and its confirmation. The file lies next to the media."""

    class Status(models.TextChoices):
        UPLOADED = "UPLOADED"
        CONFIRMING = "CONFIRMING"
        DONE = "DONE"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    admin_id = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    target_json = models.JSONField(default=dict)
    mapping_json = models.JSONField(default=dict)
    report_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "import_job"

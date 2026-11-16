import uuid

from django.db import models


class RetentionJob(models.Model):
    """One execution of a deletion. Counts only: no name, no e-mail, no answer.

    `run_id` is a plain string because this provider may not depend on the domain's tables, and
    the trail outlives whatever it describes.
    """

    class Trigger(models.TextChoices):
        AUTOMATIC = "automatic"
        MANUAL = "manual"
        ERASURE = "erasure"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    run_id = models.CharField(max_length=64, db_index=True)
    trigger = models.CharField(max_length=20, choices=Trigger.choices)
    admin_id = models.CharField(max_length=64, null=True, blank=True)
    policy = models.CharField(max_length=20)
    cutoff_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField()
    counts_json = models.JSONField(default=dict)
    # HMAC of an erased e-mail, answering "was this address erased"; never the address.
    fingerprint = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    class Meta:
        db_table = "retention_job"

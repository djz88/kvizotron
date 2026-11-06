"""Quiz, revision, run and attempt (modules/domain.md). They must not be conflated."""

import uuid

from django.db import models
from django.db.models import Q


class ImmutableRevision(Exception):
    """A revision that left DRAFT is never changed."""


class Quiz(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    slug = models.SlugField(max_length=80, unique=True)
    title = models.JSONField(default=dict)  # locale -> text
    default_locale = models.CharField(max_length=5)
    supported_locales = models.JSONField(default=list)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "quiz"


class QuizRevision(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"
        SUPERSEDED = "SUPERSEDED"
        ARCHIVED = "ARCHIVED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name="revisions")
    revision_no = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    snapshot_json = models.JSONField(default=dict)
    plugins_json = models.JSONField(default=dict)
    max_score = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    checksum = models.CharField(max_length=64, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "quiz_revision"
        constraints = [
            models.UniqueConstraint(fields=["quiz", "revision_no"], name="revision_no_per_quiz"),
            models.UniqueConstraint(
                fields=["quiz"], condition=Q(status="DRAFT"), name="one_draft_per_quiz"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            stored = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if stored != self.Status.DRAFT:
                raise ImmutableRevision(f"Revision {self.pk} is {stored}")
        super().save(*args, **kwargs)


class QuizRun(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        CLOSED = "CLOSED"
        ARCHIVED = "ARCHIVED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name="runs")
    run_no = models.PositiveIntegerField()
    current_revision = models.ForeignKey(QuizRevision, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "quiz_run"
        constraints = [
            models.UniqueConstraint(fields=["quiz", "run_no"], name="run_no_per_quiz"),
            models.UniqueConstraint(
                fields=["quiz"], condition=Q(status="OPEN"), name="one_open_run_per_quiz"
            ),
        ]


class Attempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS"
        SUBMITTED = "SUBMITTED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    run = models.ForeignKey(QuizRun, on_delete=models.PROTECT, related_name="attempts")
    revision = models.ForeignKey(QuizRevision, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    max_score = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    correct_count = models.PositiveIntegerField(null=True, blank=True)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    submission_key = models.CharField(max_length=64, unique=True, null=True, blank=True)

    class Meta:
        db_table = "attempt"
        indexes = [models.Index(fields=["run", "submitted_at"], name="attempt_run_submitted")]

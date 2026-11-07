"""Quiz, revision, run and attempt (modules/domain.md). They must not be conflated."""

import uuid
from datetime import datetime

from django.db import models
from django.db.models import Q


class ImmutableRevision(Exception):
    """A revision that left DRAFT is never changed."""


class Quiz(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    slug = models.SlugField(max_length=80, unique=True)
    title = models.JSONField(default=dict)  # locale -> text
    description = models.JSONField(default=dict)  # locale -> text
    default_locale = models.CharField(max_length=5)
    supported_locales = models.JSONField(default=list)
    featured = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "quiz"


class AppSetting(models.Model):
    """One value per key and scope: global when `quiz` is empty, otherwise that quiz's override."""

    key = models.CharField(max_length=80)
    value_json = models.JSONField()
    quiz = models.ForeignKey(Quiz, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = "app_setting"
        constraints = [
            models.UniqueConstraint(
                fields=["key"], condition=Q(quiz__isnull=True), name="one_global_value_per_key"
            ),
            models.UniqueConstraint(
                fields=["key", "quiz"],
                condition=Q(quiz__isnull=False),
                name="one_override_per_key_and_quiz",
            ),
        ]


class _WithoutTestCopies(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().exclude(status="TEST_COPY")


class QuizRevision(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"
        SUPERSEDED = "SUPERSEDED"
        ARCHIVED = "ARCHIVED"
        TEST_COPY = "TEST_COPY"  # frozen draft behind a test link; never part of the history

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name="revisions")
    revision_no = models.PositiveIntegerField(null=True, blank=True)  # a test copy has none
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    snapshot_json = models.JSONField(default=dict)
    plugins_json = models.JSONField(default=dict)
    max_score = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    checksum = models.CharField(max_length=64, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    # The default also serves `quiz.revisions`, so what is not looking for a copy never meets one.
    objects = _WithoutTestCopies()
    all_kinds = models.Manager()

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
            rows = type(self).all_kinds.filter(pk=self.pk)
            stored = rows.values_list("status", flat=True).first()
            if stored != self.Status.DRAFT:
                raise ImmutableRevision(f"Revision {self.pk} is {stored}")
        super().save(*args, **kwargs)


class QuestionBank(models.Model):
    """Questions shared by all admins. Quizzes draw from a copy made at publication."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    name = models.CharField(max_length=120)
    created_by = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "question_bank"


class BankQuestion(models.Model):
    """`question_json` has the shape of a quiz question in a draft."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    bank = models.ForeignKey(QuestionBank, on_delete=models.PROTECT, related_name="questions")
    question_json = models.JSONField(default=dict)
    tags = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bank_question"


class _NormalRuns(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(kind="normal")


class QuizRun(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        CLOSED = "CLOSED"
        ARCHIVED = "ARCHIVED"

    class Kind(models.TextChoices):
        NORMAL = "normal"
        TEST = "test"  # behind a test link; counts for nothing (ADR-0044)

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name="runs")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.NORMAL)
    run_no = models.PositiveIntegerField(null=True, blank=True)  # a test run has none
    current_revision = models.ForeignKey(QuizRevision, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # The default also serves `quiz.runs`, so results and statistics never meet a test run.
    objects = _NormalRuns()
    all_kinds = models.Manager()

    class Meta:
        db_table = "quiz_run"
        constraints = [
            models.UniqueConstraint(
                fields=["quiz", "run_no"], condition=Q(kind="normal"), name="run_no_per_quiz"
            ),
            models.UniqueConstraint(
                fields=["quiz"],
                condition=Q(status="OPEN", kind="normal"),
                name="one_open_run_per_quiz",
            ),
        ]

    def current_row(self) -> RunRevision:
        return self.revision_rows.get(active_to__isnull=True)


class RunRevision(models.Model):
    """Which revisions a round used and when. `current_revision` is what new attempts get."""

    class SwitchMode(models.TextChoices):
        FINISH = "finish"
        SWITCH = "switch"

    run = models.ForeignKey(QuizRun, on_delete=models.PROTECT, related_name="revision_rows")
    revision = models.ForeignKey(QuizRevision, on_delete=models.PROTECT)
    active_from = models.DateTimeField()
    active_to = models.DateTimeField(null=True, blank=True)
    max_score = models.DecimalField(max_digits=12, decimal_places=4)
    switch_mode = models.CharField(
        max_length=10, choices=SwitchMode.choices, default=SwitchMode.FINISH
    )

    class Meta:
        db_table = "run_revision"
        constraints = [
            models.UniqueConstraint(
                fields=["run"], condition=Q(active_to__isnull=True), name="one_current_row_per_run"
            ),
        ]


class Attempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS"
        SUBMITTED = "SUBMITTED"
        SWITCHED = "SWITCHED"
        PENDING_GRADING = "PENDING_GRADING"

    FINISHED = (Status.SUBMITTED, Status.PENDING_GRADING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    run = models.ForeignKey(QuizRun, on_delete=models.PROTECT, related_name="attempts")
    revision = models.ForeignKey(QuizRevision, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    # What the server gave on submit; the score is this plus what admins decide.
    auto_score = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    max_score = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    correct_count = models.PositiveIntegerField(null=True, blank=True)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    submission_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    replaced_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    # Empty on attempts older than these fields: all questions, default behaviour.
    selection_json = models.JSONField(null=True, blank=True)
    settings_json = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "attempt"
        indexes = [models.Index(fields=["run", "submitted_at"], name="attempt_run_submitted")]


class AttemptAnswer(models.Model):
    """One question of a submitted attempt, kept when settings say so or when a person must grade.

    `store_answers` decides, and a photo is always kept. A replaced attempt has none.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question_id = models.CharField(max_length=64)
    answer_json = models.JSONField()
    auto_points = models.DecimalField(max_digits=12, decimal_places=4)
    manual_max = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    manual_points = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    graded_by = models.CharField(max_length=64, null=True, blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)
    asset_id = models.CharField(max_length=64, null=True, blank=True)
    removed = models.BooleanField(default=False)
    approved = models.BooleanField(default=False)

    class Meta:
        db_table = "attempt_answer"
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question_id"], name="attempt_answer_one_per_question"
            )
        ]


class HiddenAnswerValue(models.Model):
    """A free-text value an admin took off a public walkthrough. The answers themselves stay."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    run = models.ForeignKey(QuizRun, on_delete=models.CASCADE, related_name="hidden_values")
    question_id = models.CharField(max_length=64)
    value_key = models.CharField(max_length=128)
    hidden_by = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hidden_answer_value"
        constraints = [
            models.UniqueConstraint(
                fields=["run", "question_id", "value_key"], name="hidden_value_once"
            )
        ]


class RunTestLink(models.Model):
    """What is only about the link. Its run holds the attempts."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    run = models.OneToOneField(QuizRun, on_delete=models.PROTECT, related_name="test_link")
    token = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "test_link"

    def is_playable(self, now: datetime) -> bool:
        """A cancelled link closed its run. An end date and archiving change nothing stored."""
        run = self.run
        return (
            run.status == QuizRun.Status.OPEN
            and (self.expires_at is None or now <= self.expires_at)
            and run.quiz.archived_at is None
        )

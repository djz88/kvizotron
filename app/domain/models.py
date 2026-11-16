"""Quiz, revision, run and attempt (modules/domain.md). They must not be conflated."""

import uuid
from datetime import datetime

from django.db import models
from django.db.models import Q
from django.utils import timezone


class ImmutableRevision(Exception):
    """A revision that left DRAFT is never changed."""


class Quiz(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    slug = models.SlugField(max_length=80, unique=True)
    title = models.JSONField(default=dict)  # locale -> text
    description = models.JSONField(default=dict)  # locale -> text
    anonymous_label = models.JSONField(default=dict)  # locale -> text with NN; lives with the quiz
    default_locale = models.CharField(max_length=5)
    supported_locales = models.JSONField(default=list)
    featured = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_by = models.CharField(max_length=64, blank=True)  # admin id, like QuestionBank
    quiz_type = models.CharField(max_length=64, blank=True, default="")  # id of the applied type
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


class BrandingConfiguration(models.Model):
    """The identity of the pages: global when `quiz` is empty, otherwise that quiz's override."""

    quiz = models.ForeignKey(Quiz, null=True, blank=True, on_delete=models.PROTECT)
    theme_id = models.CharField(max_length=80)
    texts_json = models.JSONField(default=dict)  # {"name": {"cs": "…"}, "motto": …}
    tokens_json = models.JSONField(default=dict)  # {"main": "#rrggbb", "accent": "#rrggbb"}
    # {"logo": {"asset": "<id>", "source": "<address>" | None}}; an older value is the id alone
    assets_json = models.JSONField(default=dict)

    class Meta:
        db_table = "branding_configuration"
        constraints = [
            models.UniqueConstraint(
                models.Value(1),
                condition=Q(quiz__isnull=True),
                name="one_global_branding",
            ),
            models.UniqueConstraint(
                fields=["quiz"],
                condition=Q(quiz__isnull=False),
                name="one_branding_override_per_quiz",
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


class BankFolder(models.Model):
    """A folder of one bank, at most four levels deep (`app/domain/bank_folders.py`)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    bank = models.ForeignKey(QuestionBank, on_delete=models.PROTECT, related_name="folders")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bank_folder"


class BankQuestion(models.Model):
    """`question_json` has the shape of a quiz question in a draft."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    bank = models.ForeignKey(QuestionBank, on_delete=models.PROTECT, related_name="questions")
    folder = models.ForeignKey(
        BankFolder, null=True, blank=True, on_delete=models.PROTECT, related_name="questions"
    )
    question_json = models.JSONField(default=dict)
    tags = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bank_question"


class _NormalRuns(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(kind="normal")


def _now() -> datetime:
    return timezone.now()


class QuizRun(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED"
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
    opened_at = models.DateTimeField(null=True, blank=True, default=_now)  # planned: not yet
    closed_at = models.DateTimeField(null=True, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)  # when a plan opens
    deadline_at = models.DateTimeField(null=True, blank=True)
    attempt_limit_sec = models.PositiveIntegerField(null=True, blank=True)  # fixed once it opens
    # Rules about participants, copied from the settings when planned or opened.
    participant_rules_json = models.JSONField(default=dict)
    # What the run keeps and for how long, copied from the settings when planned or opened.
    retention_json = models.JSONField(default=dict)
    data_deleted_at = models.DateTimeField(null=True, blank=True)  # the run keeps only a summary
    retention_held_at = models.DateTimeField(null=True, blank=True)  # waits for an admin to confirm
    retention_summary_json = models.JSONField(default=dict)  # read instead of the deleted rows
    results_json = models.JSONField(default=dict)  # scoreboard settings and tie seed (ADR-0051)
    rewards_json = models.JSONField(default=dict)  # reward settings fixed when planned or opened
    stateless_submitted = models.PositiveIntegerField(default=0)
    # The last anonymous number given to a participant; never goes down, so no number comes back
    participant_seq = models.PositiveIntegerField(default=0)
    access_code_hash = models.CharField(max_length=128, blank=True)
    # The run whose public board also shows this run's rows; only the display is shared (ADR-0065)
    board_main = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="board_members"
    )

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
                condition=Q(status__in=("SCHEDULED", "OPEN"), kind="normal"),
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


class Participant(models.Model):
    """One browser in one run. The cookie is stored only as a hash; it is not one person."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    run = models.ForeignKey(QuizRun, on_delete=models.CASCADE, related_name="participants")
    anonymous_key_hash = models.CharField(max_length=64)
    display_name = models.CharField(max_length=40, blank=True)
    name_key = models.CharField(max_length=80, blank=True)  # casefold() can lengthen a name
    name_dropped = models.BooleanField(default=False)  # a taken name was left out of a submission
    email = models.CharField(max_length=254, null=True, blank=True)
    # The address stripped and casefolded, so an erasure search is one indexed query.
    # Personal data like `email`: it goes with the row.
    # casefold() can lengthen an address up to three times (a ligature becomes three letters)
    email_key = models.CharField(max_length=762, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # The anonymous label's number in the run, stored so an erasure shifts no other label.
    # `participants.find_or_create` gives the next one; a row made elsewhere may lack it.
    number = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "participant"
        constraints = [
            models.UniqueConstraint(
                fields=["run", "anonymous_key_hash"], name="participant_key_per_run"
            ),
            models.UniqueConstraint(fields=["run", "number"], name="participant_number_per_run"),
        ]
        indexes = [models.Index(fields=["run", "name_key"], name="participant_run_name")]


class Attempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS"
        SUBMITTED = "SUBMITTED"
        SWITCHED = "SWITCHED"
        PENDING_GRADING = "PENDING_GRADING"
        ABANDONED = "abandoned"  # a person started again; counts for nothing

    FINISHED = (Status.SUBMITTED, Status.PENDING_GRADING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    run = models.ForeignKey(QuizRun, on_delete=models.PROTECT, related_name="attempts")
    participant = models.ForeignKey(
        "Participant", null=True, blank=True, on_delete=models.PROTECT, related_name="attempts"
    )
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

    The data profile decides: "answers" and "detailed" keep every answered question, and what a
    person must grade is always kept. A replaced attempt has none.
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
    # Scheme, host and port the admin wants this link shown with; empty: the admin's own address.
    shown_origin = models.CharField(max_length=200, blank=True, default="")

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


class RewardRule(models.Model):
    """A reward of a run, or of the quiz's template when `run` is empty. A run gets copies."""

    class Kind(models.TextChoices):
        THRESHOLD = "threshold"
        PARTICIPATION = "participation"
        MANUAL = "manual"
        DRAW = "draw"

    class Unit(models.TextChoices):
        PERCENT = "percent"
        POINTS = "points"
        CORRECT = "correct"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name="reward_rules")
    run = models.ForeignKey(
        QuizRun, null=True, blank=True, on_delete=models.CASCADE, related_name="reward_rules"
    )
    position = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    threshold_unit = models.CharField(max_length=10, choices=Unit.choices, null=True, blank=True)
    threshold_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    # Who may be drawn; both empty means everyone with an official attempt.
    min_unit = models.CharField(max_length=10, choices=Unit.choices, null=True, blank=True)
    min_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    winners = models.PositiveIntegerField(null=True, blank=True)
    alternates = models.PositiveIntegerField(null=True, blank=True)
    texts_json = models.JSONField(default=dict)  # {locale: {"name", "description", "claim"}}
    winners_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reward_rule"
        indexes = [models.Index(fields=["quiz", "run"], name="reward_rule_owner")]


class RewardEntitlement(models.Model):
    class Status(models.TextChoices):
        GRANTED = "granted"
        HANDED_OVER = "handed_over"
        CANCELLED = "cancelled"

    class Source(models.TextChoices):
        AUTO = "auto"
        MANUAL = "manual"
        DRAW = "draw"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    run = models.ForeignKey(QuizRun, on_delete=models.CASCADE, related_name="entitlements")
    rule = models.ForeignKey(RewardRule, on_delete=models.PROTECT, related_name="entitlements")
    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="entitlements"
    )
    attempt = models.ForeignKey(Attempt, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GRANTED)
    source = models.CharField(max_length=10, choices=Source.choices)
    reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    changed_at = models.DateTimeField(null=True, blank=True)
    changed_by = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "reward_entitlement"
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "participant"],
                condition=~Q(status="cancelled"),
                name="entitlement_once_per_rule",
            )
        ]


class Draw(models.Model):
    """One action of a draw. Never updated after insert: a later action is a new row."""

    class Action(models.TextChoices):
        DRAW = "draw"
        REDRAW = "redraw"
        MOVE_UP = "move_up"
        SUBSTITUTE = "substitute"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    run = models.ForeignKey(QuizRun, on_delete=models.PROTECT, related_name="draws")
    rule = models.ForeignKey(RewardRule, on_delete=models.PROTECT, related_name="draws")
    action = models.CharField(max_length=20, choices=Action.choices)
    # The draw or redraw this action amends; a redraw points at the one it supersedes.
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    admin_id = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    eligible_count = models.PositiveIntegerField()
    eligible_set_hash = models.CharField(max_length=64)
    algorithm = models.CharField(max_length=64)
    rules_version = models.CharField(max_length=64)  # sha256 of the rule's structure fields
    reason = models.CharField(max_length=200, blank=True)  # required except for `draw`
    audit_json = models.JSONField(default=dict)

    class Meta:
        db_table = "draw"


class DrawEntry(models.Model):
    """Who a draw picked. `pseudonym` stays when the participant link is dropped."""

    class Role(models.TextChoices):
        WINNER = "winner"
        ALTERNATE = "alternate"
        OUT = "out"

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    draw = models.ForeignKey(Draw, on_delete=models.CASCADE, related_name="entries")
    participant = models.ForeignKey(
        Participant, null=True, blank=True, on_delete=models.SET_NULL, related_name="draw_entries"
    )
    pseudonym = models.CharField(max_length=64)  # salted_hmac("kvz-draw", participant id)
    position = models.PositiveIntegerField()
    role = models.CharField(max_length=10, choices=Role.choices)

    class Meta:
        db_table = "draw_entry"

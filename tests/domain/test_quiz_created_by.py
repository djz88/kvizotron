"""D1 addendum: a quiz remembers which admin created it, and its creator's e-mail is findable."""

import importlib
from datetime import timedelta

import pytest
from django.utils import timezone

from app.domain import authoring
from app.domain.creator import creator_email
from app.domain.models import Quiz
from app.kernel.models import AdminUser, AuditEvent
from tests.domain.helpers import ADMIN_ID, make_quiz

pytestmark = pytest.mark.django_db
migration = importlib.import_module("app.domain.migrations.0018_quiz_created_by")


def test_duplicate_records_the_creator():
    source = make_quiz()
    copied = authoring.duplicate_quiz(source, "kopie", admin_id=ADMIN_ID)
    assert copied.created_by == ADMIN_ID
    assert source.created_by == ""


def test_creator_email_is_empty_when_unknown():
    assert creator_email(make_quiz()) == ""
    assert creator_email(make_quiz(slug="x", created_by="not-a-uuid")) == ""
    assert creator_email(make_quiz(slug="y", created_by=ADMIN_ID)) == ""


def test_creator_email_comes_from_the_account():
    admin = AdminUser.objects.create_admin("carol", "x-y-z-long-password-1")
    admin.email = "carol@example.org"
    admin.save()
    assert creator_email(make_quiz(created_by=str(admin.pk))) == "carol@example.org"


def test_backfill_prefers_the_oldest_audit_event_then_the_oldest_admin():
    """AC-99."""
    first = AdminUser.objects.create_admin("first", "x-y-z-long-password-1")
    second = AdminUser.objects.create_admin("second", "x-y-z-long-password-1")
    audited = make_quiz(slug="a")
    unaudited = make_quiz(slug="b")
    done = make_quiz(slug="c", created_by="keep")
    now = timezone.now()
    for actor, age in ((second, 1), (first, 5)):
        event = AuditEvent.objects.create(
            actor_type="admin",
            actor_id=str(actor.pk),
            action="quiz.created",
            entity_type="quiz",
            entity_id=str(audited.id),
        )
        AuditEvent.objects.filter(pk=event.pk).update(created_at=now - timedelta(days=age))
    AuditEvent.objects.create(
        actor_type="participant",
        actor_id="p",
        action="x",
        entity_type="quiz",
        entity_id=str(unaudited.id),
    )
    AdminUser.objects.filter(pk=first.pk).update(created_at=now - timedelta(days=9))

    migration.fill_created_by(Quiz, AuditEvent, AdminUser)

    for quiz in (audited, unaudited, done):
        quiz.refresh_from_db()
    assert audited.created_by == str(first.pk)
    assert unaudited.created_by == str(first.pk)
    assert done.created_by == "keep"


def test_backfill_leaves_quizzes_empty_without_any_admin():
    quiz = make_quiz()
    migration.fill_created_by(Quiz, AuditEvent, AdminUser)
    quiz.refresh_from_db()
    assert quiz.created_by == ""

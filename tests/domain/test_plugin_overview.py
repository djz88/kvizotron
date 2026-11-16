"""AC-125: where a value of a module's setting differs from the global one."""

import pytest
from django.conf import settings as django_settings
from django.utils import timezone

from app.domain import authoring, plugin_overview, settings
from app.domain.models import AppSetting, QuizRevision
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db
KEY = "photo_visibility"
MODULE = "question.image_answer"


def manifest(module_id=MODULE):
    return next(m for m in django_settings.KVZ_MODULES if m.id == module_id)


def only(module_id=MODULE, key=KEY):
    return next(row for row in plugin_overview.overview(manifest(module_id)) if row.key == key)


def set_question_value(quiz, value, key=KEY, *, published=False):
    """Writes the value straight into the stored question, as an editor save would."""
    status = QuizRevision.Status.PUBLISHED if published else QuizRevision.Status.DRAFT
    if not published:
        authoring.get_draft(quiz)
    revision = quiz.revisions.filter(status=status).first()
    snapshot = revision.snapshot_json
    snapshot["questions"][0]["settings"][key] = value
    QuizRevision.objects.filter(pk=revision.pk).update(snapshot_json=snapshot)


def rows(row=None):
    row = row or only()
    return [(d.quiz.slug, d.value, d.question_no) for d in row.differences]


def test_quiz_override_that_differs_is_listed():
    quiz = published_quiz()
    settings.set_override(KEY, quiz, "admins", admin_id=ADMIN_ID)
    assert only().global_value == "author"
    assert rows() == [(quiz.slug, "admins", None)]


def test_override_equal_to_global_is_not_listed():
    settings.set_override(KEY, published_quiz(), "author", admin_id=ADMIN_ID)
    assert rows() == []


def test_question_value_is_listed_with_its_number():
    quiz = published_quiz(questions=2)
    set_question_value(quiz, "public")
    row = only()
    assert rows(row) == [(quiz.slug, "public", 1)]
    assert (
        row.differences[0].question_id
        == authoring.get_draft(quiz).snapshot_json["questions"][0]["id"]
    )


def test_question_value_equal_to_global_is_not_listed_even_if_quiz_differs():
    quiz = published_quiz()
    settings.set_override(KEY, quiz, "admins", admin_id=ADMIN_ID)
    set_question_value(quiz, "author")
    assert rows() == [(quiz.slug, "admins", None)]


def test_draft_wins_over_the_published_revision():
    quiz = published_quiz()
    set_question_value(quiz, "public", published=True)
    authoring.get_draft(quiz)
    set_question_value(quiz, "author")
    assert rows() == []


def test_published_revision_is_read_when_there_is_no_draft():
    quiz = published_quiz()
    set_question_value(quiz, "public", published=True)
    assert not quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()
    assert rows() == [(quiz.slug, "public", 1)]


def test_archived_quiz_is_left_out():
    quiz = published_quiz()
    settings.set_override(KEY, quiz, "admins", admin_id=ADMIN_ID)
    set_question_value(quiz, "public")
    type(quiz).objects.filter(pk=quiz.pk).update(archived_at=timezone.now())
    assert rows() == []


def test_a_value_no_longer_offered_counts_as_none():
    quiz = published_quiz()
    AppSetting.objects.create(key=KEY, quiz=quiz, value_json="retired")
    set_question_value(quiz, "retired")
    assert rows() == []


def test_setting_without_question_scope_has_no_question_rows():
    quiz = published_quiz()
    set_question_value(quiz, "indigo_pink", key="color_palette")
    assert only("theme.default", "color_palette").differences == []


def test_unset_global_counts_as_the_default():
    assert not AppSetting.objects.filter(key=KEY, quiz__isnull=True).exists()
    assert only().global_value == "author"


def test_changed_global_is_what_is_compared():
    quiz = published_quiz()
    settings.set_override(KEY, quiz, "admins", admin_id=ADMIN_ID)
    settings.set_global(KEY, "admins", admin_id=ADMIN_ID)
    assert only().global_value == "admins"
    assert rows() == []


def test_list_is_cut_to_the_limit_and_total_is_kept(monkeypatch):
    monkeypatch.setattr(plugin_overview, "LIMIT", 2)
    for number in range(3):
        settings.set_override(KEY, published_quiz(f"k{number}"), "admins", admin_id=ADMIN_ID)
    row = only()
    assert len(row.differences) == 2
    assert row.total == 3


def test_module_without_settings_gives_an_empty_list():
    assert plugin_overview.overview(manifest("question.choice")) == []


def test_a_quiz_row_comes_before_its_questions():
    quiz = published_quiz()
    settings.set_override(KEY, quiz, "admins", admin_id=ADMIN_ID)
    set_question_value(quiz, "public")
    assert [d.question_no for d in only().differences] == [None, 1]

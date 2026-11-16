"""Test links: fixed to one version, ended by time, by cancelling or by archiving (ADR-0044)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from app.domain import attempts, authoring, banks, run_links
from app.domain.models import Attempt, QuizRevision, QuizRun, RunRevision, RunTestLink
from app.kernel.models import AuditEvent
from tests.domain.helpers import (
    ADMIN_ID,
    add_question,
    add_row,
    bank_with,
    make_quiz,
    published_quiz,
)

pytestmark = pytest.mark.django_db


def link_on(quiz, revision=None, expires_at=None):
    return run_links.create(quiz, revision, expires_at=expires_at, admin_id=ADMIN_ID)


def played(link):
    return attempts.start(link.run)


def prompts(run):
    questions = run.current_revision.snapshot_json["questions"]
    return [question["definition"]["prompt"]["cs"] for question in questions]


def test_link_on_a_published_revision_plays_it_through_attempts_start():
    quiz = published_quiz()
    published = authoring.latest_published(quiz)
    link = link_on(quiz, published)
    started = played(link)
    assert started.attempt.revision == published
    assert started.attempt.run.kind == QuizRun.Kind.TEST


def test_later_publish_and_draft_edit_leave_link_version_unchanged():
    quiz = published_quiz()
    published = authoring.latest_published(quiz)
    link = link_on(quiz, published)
    add_question(quiz, prompt="Další")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    add_question(quiz, prompt="Ještě další")
    assert played(link).attempt.revision == published


def test_draft_copy_does_not_change_the_draft_and_keeps_its_content_after_edits():
    quiz = make_quiz()
    add_question(quiz, prompt="První")
    link = link_on(quiz)
    draft = quiz.revisions.get(status=QuizRevision.Status.DRAFT)
    assert draft.published_at is None
    assert link.run.current_revision.status == QuizRevision.Status.TEST_COPY
    add_question(quiz, prompt="Druhá")
    link.run.refresh_from_db()
    assert prompts(link.run) == ["První cs"]
    assert authoring.latest_published(quiz) is None
    assert played(link).attempt.revision == link.run.current_revision


def test_copy_survives_bank_question_edit_and_delete():
    quiz = make_quiz()
    bank = bank_with(2)
    add_row(quiz, bank, count=1)
    link = link_on(quiz)
    frozen = link.run.current_revision.snapshot_json["draws"][0]["pool"]
    assert len(frozen) == 2
    for question in bank.questions.all():
        banks.delete_question(bank, question.pk, admin_id=ADMIN_ID)
    started = played(link)
    assert len(attempts.questions_of(started.attempt)) == 1


def test_draft_failing_publication_check_raises_with_problems():
    quiz = make_quiz()
    with pytest.raises(authoring.PublicationError) as error:
        link_on(quiz)
    assert error.value.problems
    assert not RunTestLink.objects.exists()
    assert not QuizRevision.all_kinds.filter(quiz=quiz).exists()


def test_archived_quiz_refuses_a_new_link():
    quiz = published_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        link_on(quiz, QuizRevision.objects.filter(quiz=quiz).first())


def test_links_each_get_own_run_and_token():
    quiz = published_quiz()
    published = authoring.latest_published(quiz)
    first, second = link_on(quiz, published), link_on(quiz, published)
    assert first.run_id != second.run_id
    assert first.token != second.token
    assert len(first.token) >= 43
    assert run_links.find_playable(first.token) == first


def test_expired_link_refuses_start_submit_and_check():
    quiz = published_quiz()
    link = link_on(quiz, authoring.latest_published(quiz))
    started = played(link)
    RunTestLink.objects.filter(pk=link.pk).update(expires_at=timezone.now() - timedelta(seconds=5))
    link.run.refresh_from_db()
    assert run_links.find_playable(link.token) is None
    with pytest.raises(attempts.AttemptError) as error:
        attempts.start(QuizRun.all_kinds.get(pk=link.run_id))
    assert error.value.code == "test_link_ended"
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(started.attempt.id, started.token, {}, started.submission_key)
    assert error.value.code == "test_link_ended"
    with pytest.raises(attempts.AttemptError) as error:
        attempts.check(started.attempt.id, started.token, "x")
    assert error.value.code == "test_link_ended"


def test_end_in_the_future_still_plays():
    quiz = published_quiz()
    link = link_on(
        quiz, authoring.latest_published(quiz), expires_at=timezone.now() + timedelta(hours=1)
    )
    assert run_links.find_playable(link.token) == link
    assert played(link).attempt


def test_cancelled_link_refuses_submit_from_an_open_page_and_keeps_attempts():
    quiz = published_quiz()
    link = link_on(quiz, authoring.latest_published(quiz))
    started = played(link)
    run_links.cancel(link, admin_id=ADMIN_ID)
    assert run_links.find_playable(link.token) is None
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(started.attempt.id, started.token, {}, started.submission_key)
    assert error.value.code == "test_link_ended"
    assert Attempt.objects.filter(run=link.run).count() == 1


def test_a_normal_closed_run_keeps_its_own_error():
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    started = attempts.start(run)
    authoring.close_run(run, admin_id=ADMIN_ID)
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(started.attempt.id, started.token, {}, started.submission_key)
    assert error.value.code == "run_closed"


def test_archived_quiz_stops_its_links_and_restore_resumes_them():
    quiz = published_quiz()
    link = link_on(quiz, authoring.latest_published(quiz))
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    assert run_links.find_playable(link.token) is None
    with pytest.raises(attempts.AttemptError) as error:
        attempts.start(QuizRun.all_kinds.get(pk=link.run_id))
    assert error.value.code == "test_link_ended"
    authoring.restore_quiz(quiz, admin_id=ADMIN_ID)
    assert run_links.find_playable(link.token) == link


def test_delete_removes_link_attempts_rows_and_copy_and_nothing_else():
    quiz = make_quiz()
    add_question(quiz)
    link = link_on(quiz)
    played(link)
    copy = link.run.current_revision
    run_id = link.run_id
    run_links.delete(link, admin_id=ADMIN_ID)
    assert not RunTestLink.objects.exists()
    assert not Attempt.objects.exists()
    assert not RunRevision.objects.exists()
    assert not QuizRun.all_kinds.filter(pk=run_id).exists()
    assert not QuizRevision.all_kinds.filter(pk=copy.pk).exists()
    assert quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()


def test_delete_keeps_a_published_revision_and_other_attempts():
    quiz = published_quiz()
    published = authoring.latest_published(quiz)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    attempts.start(run)
    link = link_on(quiz, published)
    played(link)
    run_links.delete(link, admin_id=ADMIN_ID)
    assert authoring.latest_published(quiz) == published
    assert Attempt.objects.filter(run=run).count() == 1


def test_delete_attempts_keeps_the_link_playable():
    quiz = published_quiz()
    link = link_on(quiz, authoring.latest_published(quiz))
    played(link)
    run_links.delete_attempts(link, admin_id=ADMIN_ID)
    assert not Attempt.objects.exists()
    assert played(link).attempt


def test_each_change_is_audited_without_the_token():
    quiz = published_quiz()
    link = link_on(quiz, authoring.latest_published(quiz))
    token = link.token
    run_links.delete_attempts(link, admin_id=ADMIN_ID)
    run_links.cancel(link, admin_id=ADMIN_ID)
    run_links.delete(link, admin_id=ADMIN_ID)
    rows = AuditEvent.objects.filter(action__startswith="test_link.")
    assert {row.action for row in rows} == {
        "test_link.created",
        "test_link.attempts_deleted",
        "test_link.cancelled",
        "test_link.deleted",
    }
    assert all(token not in str(row.details_json) for row in rows)


@pytest.mark.parametrize(
    ("typed", "origin"),
    [
        ("192.168.1.10:8443", "https://192.168.1.10:8443"),
        ("http://kviz.example.cz/", "http://kviz.example.cz"),
        ("https://[::1]:8443", "https://[::1]:8443"),
        (" HTTPS://Kviz.Example.cz ", "https://kviz.example.cz"),
        ("localhost", "https://localhost"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_clean_origin_accepts_host_ip_and_port(typed, origin):
    assert run_links.clean_origin(typed) == origin


@pytest.mark.parametrize(
    "typed",
    [
        "https://a.cz/t/x",
        "https://a.cz?x=1",
        "https://a.cz#x",
        "https://user@a.cz",
        "https://a.cz:0",
        "https://a.cz:65536",
        "https://a.cz:port",
        "javascript:alert(1)",
        "ftp://a.cz",
        "a b.cz",
        "https://-a.cz",
        "https://a..cz",
        "https://[::1",
        "https://[::1%<b>]",
        'https://[fe80::1%"onx=y]',
        "https://[fe80::1%'x]:80",
        "https://[fe80::1%]]",
        "https://999.1.1.1",
        "https://1.2.3",
        "https://123",
        "192.168.1.1000:8443",
        "https://",
        "https://" + "a" * 200,
    ],
)
def test_clean_origin_refuses_anything_else(typed):
    with pytest.raises(run_links.OriginInvalid):
        run_links.clean_origin(typed)


def test_set_origin_saves_only_that_link_and_audits_without_the_value():
    """AC-167: the shown address is saved with that one link and changes nothing else."""
    quiz = published_quiz()
    published = authoring.latest_published(quiz)
    end = timezone.now() + timedelta(days=2)
    first = link_on(quiz, published, expires_at=end)
    second = link_on(quiz, published)
    token = first.token
    run_links.set_origin(first, "10.0.0.5:8080", admin_id=ADMIN_ID)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.shown_origin == "https://10.0.0.5:8080"
    assert second.shown_origin == ""
    assert first.token == token
    assert first.expires_at == end
    rows = AuditEvent.objects.filter(action="test_link.address_changed")
    assert rows.count() == 1
    details = str(rows.get().details_json)
    assert "10.0.0.5" not in details
    assert token not in details


def test_set_origin_with_a_bad_value_saves_nothing():
    quiz = published_quiz()
    link = link_on(quiz, authoring.latest_published(quiz))
    run_links.set_origin(link, "a.cz", admin_id=ADMIN_ID)
    with pytest.raises(run_links.OriginInvalid):
        run_links.set_origin(link, "https://b.cz/x", admin_id=ADMIN_ID)
    link.refresh_from_db()
    assert link.shown_origin == "https://a.cz"
    assert AuditEvent.objects.filter(action="test_link.address_changed").count() == 1


def test_set_origin_is_refused_for_an_archived_quiz():
    quiz = published_quiz()
    link = link_on(quiz, authoring.latest_published(quiz))
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    link.refresh_from_db()
    with pytest.raises(authoring.QuizArchived):
        run_links.set_origin(link, "a.cz", admin_id=ADMIN_ID)

"""A test run and a test copy exist only for their link. Every other query must not see them."""

import secrets
from datetime import timedelta

import pytest
from django.utils import timezone

from app.domain import authoring, quiz_state, run_links, usage
from app.domain.models import ImmutableRevision, QuizRevision, QuizRun, RunRevision, RunTestLink
from app.kernel.models import AdminUser
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in():
    client = FormClient()
    client.force_login(AdminUser.objects.create_admin("alice", "dlouhe-a-neobvykle-heslo"))
    return client


def make_test_run(quiz, revision=None):
    revision = revision or authoring.latest_published(quiz)
    run = QuizRun.all_kinds.create(
        quiz=quiz, kind=QuizRun.Kind.TEST, run_no=None, current_revision=revision
    )
    RunRevision.objects.create(
        run=run, revision=revision, active_from=timezone.now(), max_score=revision.max_score
    )
    RunTestLink.objects.create(run=run, token=secrets.token_urlsafe(32), created_by=ADMIN_ID)
    return run


def make_test_copy(quiz):
    return QuizRevision.all_kinds.create(
        quiz=quiz,
        revision_no=None,
        status=QuizRevision.Status.TEST_COPY,
        snapshot_json=authoring.future_snapshot(quiz),
    )


def test_two_active_test_runs_and_a_normal_run_can_coexist():
    quiz = published_quiz()
    first = make_test_run(quiz)
    second = make_test_run(quiz)
    normal = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert QuizRun.all_kinds.filter(quiz=quiz, status=QuizRun.Status.OPEN).count() == 3
    assert {first.pk, second.pk} & set(QuizRun.objects.values_list("pk", flat=True)) == set()
    assert list(quiz.runs.all()) == [normal]


def test_a_second_normal_open_run_is_still_refused():
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    with pytest.raises(authoring.RunAlreadyOpen):
        authoring.open_run(quiz, admin_id=ADMIN_ID)


def test_test_run_takes_no_run_number_and_next_run_is_still_one():
    quiz = published_quiz()
    assert make_test_run(quiz).run_no is None
    assert authoring.open_run(quiz, admin_id=ADMIN_ID).run_no == 1


def test_quiz_state_ignores_test_run():
    quiz = published_quiz()
    before = quiz_state.of(quiz)
    make_test_run(quiz)
    assert quiz_state.of(quiz) == before


def test_public_quiz_page_and_landing_never_show_a_test_run():
    quiz = published_quiz()
    make_test_run(quiz)
    client = FormClient()
    assert client.get(f"/q/{quiz.slug}?lang=en").status_code == 404
    assert quiz.slug not in client.get("/?lang=en").content.decode()


def test_public_run_address_refuses_a_test_run():
    quiz = published_quiz()
    run = make_test_run(quiz)
    assert FormClient().get(f"/q/{quiz.slug}/r/{run.id}").status_code == 404


def test_admin_run_page_404s_and_run_list_omits_a_test_run(logged_in):
    quiz = published_quiz()
    run = make_test_run(quiz)
    assert logged_in.get(f"/admin/runs/{run.id}").status_code == 404
    assert str(run.id) not in logged_in.get(f"/admin/quizzes/{quiz.id}/runs").content.decode()


def test_publish_moves_no_test_run():
    quiz = published_quiz()
    run = make_test_run(quiz)
    revision = run.current_revision_id
    add_question(quiz, prompt="Další")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run.current_revision_id == revision
    assert run.revision_rows.count() == 1


def test_usage_counts_a_test_run_as_needing_its_modules():
    quiz = published_quiz()
    make_test_run(quiz)
    reasons = usage.question_type_usage("question.choice")
    assert reasons
    assert quiz.slug in reasons[0]


def test_test_copy_is_hidden_from_revision_list_and_latest_published(logged_in):
    quiz = published_quiz()
    published = authoring.latest_published(quiz)
    copy = make_test_copy(quiz)
    assert authoring.latest_published(quiz) == published
    assert list(quiz.revisions.all()) == [published]
    assert copy.pk not in QuizRevision.objects.values_list("pk", flat=True)
    page = logged_in.get(f"/admin/quizzes/{quiz.id}/revisions")
    assert page.status_code == 200


def test_a_test_copy_alone_does_not_lock_the_address(logged_in):
    """The address locks at first publication, which a copy is not."""
    quiz = make_quiz()
    add_question(quiz)
    make_test_copy(quiz)
    page = logged_in.get(f"/admin/quizzes/{quiz.id}/settings").content.decode()
    assert 'name="slug"' in page
    tag = page.split('name="slug"')[0].rsplit("<input", 1)[1] + page.split('name="slug"')[1][:200]
    assert "disabled" not in tag.split(">")[0]


def test_a_revision_list_query_for_kinds_can_still_reach_the_copy():
    quiz = published_quiz()
    copy = make_test_copy(quiz)
    assert QuizRevision.all_kinds.filter(pk=copy.pk).exists()


def test_a_saved_test_copy_is_immutable():
    copy = make_test_copy(published_quiz())
    with pytest.raises(ImmutableRevision):
        copy.save()


def test_ended_link_does_not_hold_a_module():
    quiz = published_quiz()
    link = run_links.create(
        quiz,
        authoring.latest_published(quiz),
        expires_at=timezone.now() - timedelta(minutes=1),
        admin_id=ADMIN_ID,
    )
    assert link
    assert usage.question_type_usage("question.choice") == []


def test_active_link_holds_a_module():
    quiz = published_quiz()
    run_links.create(quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID)
    assert usage.question_type_usage("question.choice")

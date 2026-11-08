"""AC-72: an access code is kept only as a hash, and a changed code changes what it unlocks."""

import base64
import string

import pytest

from app.domain import access_codes, attempts, authoring
from app.domain.models import QuizRun
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, open_quiz_run, published_quiz

pytestmark = pytest.mark.django_db
CODE = "ABCD2345"


def a_run() -> QuizRun:
    return open_quiz_run()


def test_only_hash_is_stored():
    run = a_run()
    access_codes.set_code(run, CODE, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run.access_code_hash and CODE not in run.access_code_hash
    entry = AuditEvent.objects.get(action="run.code_changed")
    assert CODE not in str(entry.details_json) and entry.details_json == {"removed": False}


def test_generated_code_uses_readable_alphabet():
    for forbidden in "ILO01":
        assert forbidden not in access_codes.ALPHABET
    assert set(access_codes.ALPHABET) <= set(string.ascii_uppercase + string.digits)
    for _ in range(50):
        code = access_codes.generate()
        assert len(code) == 8 and set(code) <= set(access_codes.ALPHABET)


def test_matches_ignores_case_and_spaces():
    run = a_run()
    access_codes.set_code(run, " abcd2345 ", admin_id=ADMIN_ID)
    assert access_codes.matches(run, "ABCD2345")
    assert access_codes.matches(run, " abcd2345")
    assert not access_codes.matches(run, "ABCD2346")


def test_start_without_unlock_is_403_code():
    run = a_run()
    access_codes.set_code(run, CODE, admin_id=ADMIN_ID)
    with pytest.raises(attempts.AttemptError) as error:
        attempts.start(run, unlocked=False)
    assert error.value.code == "code_required"


def test_unlock_token_opens_start():
    run = a_run()
    access_codes.set_code(run, CODE, admin_id=ADMIN_ID)
    token = access_codes.unlock_token(run)
    assert access_codes.is_unlocked(run, token)
    assert not access_codes.is_unlocked(run, None)
    assert not access_codes.is_unlocked(run, "garbage")
    assert attempts.start(run, unlocked=access_codes.is_unlocked(run, token)).attempt.pk


def test_changed_code_stops_unstarted_but_not_running():
    run = a_run()
    access_codes.set_code(run, CODE, admin_id=ADMIN_ID)
    old = access_codes.unlock_token(run)
    running = attempts.start(run, unlocked=True)
    access_codes.set_code(run, "WXYZ6789", admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert not access_codes.is_unlocked(run, old)
    with pytest.raises(attempts.AttemptError):
        attempts.start(run, unlocked=access_codes.is_unlocked(run, old))
    result = attempts.submit(running.attempt.id, running.token, {}, running.submission_key)
    assert result.max_points


def test_token_of_another_run_does_not_unlock():
    first, second = a_run(), authoring.open_run(published_quiz("jiny"), admin_id=ADMIN_ID)
    for run in (first, second):
        access_codes.set_code(run, CODE, admin_id=ADMIN_ID)
    assert not access_codes.is_unlocked(second, access_codes.unlock_token(first))


def test_removed_code_opens_run():
    run = a_run()
    access_codes.set_code(run, CODE, admin_id=ADMIN_ID)
    access_codes.set_code(run, None, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run.access_code_hash == ""
    assert attempts.start(run, unlocked=False).attempt.pk
    assert AuditEvent.objects.filter(
        action="run.code_changed", details_json={"removed": True}
    ).exists()


def test_code_cannot_change_on_a_closed_run():
    run = a_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    with pytest.raises(access_codes.CodeRefused):
        access_codes.set_code(run, CODE, admin_id=ADMIN_ID)


def test_test_run_ignores_the_code():
    from app.domain import run_links

    quiz = published_quiz()
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    QuizRun.all_kinds.filter(pk=link.run_id).update(access_code_hash="x")
    run = QuizRun.all_kinds.get(pk=link.run_id)
    assert attempts.start(run, unlocked=False).attempt.pk


def test_cookie_payload_holds_no_part_of_the_hash():
    run = a_run()
    access_codes.set_code(run, CODE, admin_id=ADMIN_ID)
    token = access_codes.unlock_token(run)
    payload = token.split(":")[0]
    readable = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
    for size in (6, 8, 12):
        for start in range(len(run.access_code_hash) - size):
            assert run.access_code_hash[start : start + size] not in readable
    assert access_codes.is_unlocked(run, token)


def test_locked_start_is_allowed_only_to_resume():
    from app.domain import participants

    rules = {"repeat_attempts": "forbid", "unfinished_attempt": "continue"}
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, rules=rules)
    who = participants.find_or_create(run, "k" * 20)
    first = attempts.start(run, participant=who)
    access_codes.set_code(run, CODE, admin_id=ADMIN_ID)
    again = attempts.start(run, participant=who, unlocked=False)
    assert again.attempt.pk == first.attempt.pk
    other = participants.find_or_create(run, "z" * 20)
    with pytest.raises(attempts.AttemptError) as error:
        attempts.start(run, participant=other, unlocked=False)
    assert error.value.code == "code_required"

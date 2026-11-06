import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from django.core import signing

from app.domain import attempts, tokens
from tests.domain.helpers import OPTION_A, open_quiz_run

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)


def claims():
    return tokens.AttemptClaims(
        run_id=uuid7(),
        revision_id=uuid7(),
        attempt_id=uuid7(),
        started_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        manifest_hash="abc",
    )


def payload_of(token):
    data = token.split(":")[0]
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode()


def test_round_trip():
    original = claims()
    assert tokens.verify(tokens.issue(original)) == original


@pytest.mark.parametrize("field", ["run_id", "revision_id", "attempt_id"])
def test_changed_claim_is_refused(field):
    token = tokens.issue(claims())
    body = json.loads(payload_of(token))
    body[field] = str(uuid7())
    forged = base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip("=")
    with pytest.raises(tokens.InvalidToken):
        tokens.verify(":".join([forged, *token.split(":")[1:]]))


@pytest.mark.parametrize("token", ["", "nonsense", "a:b:c"])
def test_garbage_is_refused(token):
    with pytest.raises(tokens.InvalidToken):
        tokens.verify(token)


def test_token_signed_with_other_salt_is_refused():
    with pytest.raises(tokens.InvalidToken):
        tokens.verify(signing.dumps({"attempt_id": str(uuid7())}, salt="other"))


def test_validly_signed_token_of_wrong_shape_is_refused():
    with pytest.raises(tokens.InvalidToken):
        tokens.verify(signing.dumps({"attempt_id": "x"}, salt=tokens.SALT))


@pytest.mark.django_db
def test_token_contains_no_solution():
    started = attempts.start(open_quiz_run())
    assert OPTION_A not in payload_of(started.token)
    assert "correct" not in payload_of(started.token)
    assert tokens.verify(started.token).attempt_id == started.attempt.id

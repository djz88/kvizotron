"""Signed attempt ticket (ADR-0024). Signed, not encrypted: no solutions, no personal data."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.core import signing

SALT = "kvizotron.attempt"
RESULT_SALT = "kvizotron.result"


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class AttemptClaims:
    run_id: UUID
    revision_id: UUID
    attempt_id: UUID
    started_at: datetime
    expires_at: datetime
    manifest_hash: str


def issue(claims: AttemptClaims) -> str:
    return signing.dumps(
        {
            "run_id": str(claims.run_id),
            "revision_id": str(claims.revision_id),
            "attempt_id": str(claims.attempt_id),
            "started_at": claims.started_at.isoformat(),
            "expires_at": claims.expires_at.isoformat(),
            "manifest_hash": claims.manifest_hash,
        },
        salt=SALT,
    )


def verify(token: str) -> AttemptClaims:
    try:
        data = signing.loads(token, salt=SALT)
        return AttemptClaims(
            run_id=UUID(data["run_id"]),
            revision_id=UUID(data["revision_id"]),
            attempt_id=UUID(data["attempt_id"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            manifest_hash=data["manifest_hash"],
        )
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        raise InvalidToken from exc


def issue_result(attempt_id: UUID) -> str:
    """A reference to a finished attempt. No end date until retention arrives in D3."""
    return signing.dumps(str(attempt_id), salt=RESULT_SALT)


def verify_result(token: str) -> UUID:
    try:
        return UUID(signing.loads(token, salt=RESULT_SALT))
    except (signing.BadSignature, TypeError, ValueError) as exc:
        raise InvalidToken from exc

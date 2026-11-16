"""The access code of a run (FR-06). Only a hash is kept; a code can be replaced, never read."""

import secrets
import string

from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.db import transaction
from django.utils.crypto import salted_hmac

from app.domain import authoring
from app.domain.models import QuizRun
from app.kernel import audit

# Easy to read aloud: no I, L, O, 0 or 1.
ALPHABET = "".join(
    character for character in string.ascii_uppercase + string.digits if character not in "ILO01"
)
LENGTH = 8
COOKIE_PREFIX = "kvz_c_"
COOKIE_MAX_AGE = 30 * 24 * 3600
_SALT = "kvizotron.access"


class CodeRefused(Exception):
    """The run is no longer planned or open."""


def generate() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def _normal(code: str) -> str:
    return code.strip().upper()


def cookie_name(run: QuizRun) -> str:
    return f"{COOKIE_PREFIX}{run.id.hex}"


def set_code(run: QuizRun, code: str | None, *, admin_id: str) -> None:
    """`None` or an empty code removes it. Nothing about the code reaches the audit trail."""
    authoring.ensure_editable(run.quiz)
    code = _normal(code or "")
    with transaction.atomic():
        changed = QuizRun.objects.filter(
            pk=run.pk, status__in=[QuizRun.Status.SCHEDULED, QuizRun.Status.OPEN]
        ).update(access_code_hash=make_password(code) if code else "")
        if not changed:
            raise CodeRefused(str(run.id))
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="run.code_changed",
            entity_type="run",
            entity_id=str(run.id),
            details={"removed": not code},
        )
    run.refresh_from_db(fields=["access_code_hash"])


def matches(run: QuizRun, code: str) -> bool:
    return bool(run.access_code_hash) and check_password(_normal(code), run.access_code_hash)


def _version(run: QuizRun) -> str:
    """Changes with the code, and reveals nothing of the stored hash."""
    return salted_hmac(_SALT, run.access_code_hash, algorithm="sha256").hexdigest()[:16]


def unlock_token(run: QuizRun) -> str:
    """Proof that someone entered the code that is set now. A new code makes it worthless."""
    return signing.dumps({"run": str(run.id), "v": _version(run)}, salt=_SALT, compress=False)


def is_unlocked(run: QuizRun, token: str | None) -> bool:
    if not run.access_code_hash:
        return True
    if not token:
        return False
    try:
        claims = signing.loads(token, salt=_SALT, max_age=COOKIE_MAX_AGE)
    except signing.BadSignature:
        return False
    return claims == {"run": str(run.id), "v": _version(run)}

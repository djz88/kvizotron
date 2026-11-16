"""Test links: a hidden run fixed to one version, played without an account (ADR-0044)."""

import ipaddress
import re
import secrets
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from app.domain import authoring
from app.domain.models import (
    Attempt,
    AttemptAnswer,
    Participant,
    Quiz,
    QuizRevision,
    QuizRun,
    RunRevision,
    RunTestLink,
)
from app.kernel import audit


def _audit(action: str, link: RunTestLink, admin_id: str, details: dict[str, Any] | None = None):
    """Never the token: it is a working address."""
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=f"test_link.{action}",
        entity_type="test_link",
        entity_id=str(link.id),
        details=details,
    )


def create(
    quiz: Quiz, revision: QuizRevision | None, *, expires_at: datetime | None, admin_id: str
) -> RunTestLink:
    """`revision=None` freezes a copy of the draft, which must pass the publication check."""
    authoring.ensure_editable(quiz)
    with transaction.atomic():
        chosen = revision if revision is not None else authoring.freeze_copy(quiz)
        run = QuizRun.all_kinds.create(
            quiz=quiz, kind=QuizRun.Kind.TEST, run_no=None, current_revision=chosen
        )
        RunRevision.objects.create(
            run=run, revision=chosen, active_from=run.opened_at, max_score=chosen.max_score
        )
        link = RunTestLink.objects.create(
            run=run, token=secrets.token_urlsafe(32), expires_at=expires_at, created_by=admin_id
        )
        _audit("created", link, admin_id, {"revision_no": chosen.revision_no})
    return link


MAX_ORIGIN = 200
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


class OriginInvalid(ValueError):
    pass


def _host_ok(host: str) -> bool:
    if host.startswith("["):
        if not host.endswith("]"):
            return False
        try:
            address = ipaddress.IPv6Address(host[1:-1])
        except ValueError:
            return False
        return address.scope_id is None  # a zone id would let any character in
    if host.rsplit(".", 1)[-1].isdigit():  # a browser reads it as IPv4, so it must be one
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            return False
        return True
    return all(_LABEL.fullmatch(label) for label in host.split("."))


def clean_origin(value: str) -> str:
    """`https://host:port` as typed, normalised; empty means the admin's own address."""
    typed = value.strip()
    if not typed:
        return ""
    if "://" not in typed:
        typed = f"https://{typed}"
    scheme, _sep, rest = typed.partition("://")
    scheme = scheme.lower()
    rest = rest.removesuffix("/")
    if (
        scheme not in ("http", "https")
        or not rest
        or any(char in rest for char in "/?#@\\")
        or any(char.isspace() for char in rest)
    ):
        raise OriginInvalid(_("Type only the start of the address, such as https://host:8443."))
    host, port = rest.lower(), ""
    if not host.endswith("]") and ":" in host:  # "[::1]" has colons but no port
        host, _sep, port = host.rpartition(":")
    if port and not (port.isascii() and port.isdigit() and 1 <= int(port) <= 65535):
        raise OriginInvalid(_("The port must be a number from 1 to 65535."))
    if not _host_ok(host):
        raise OriginInvalid(_("Type a host name or an IP address."))
    origin = f"{scheme}://{host}" + (f":{port}" if port else "")
    if len(origin) > MAX_ORIGIN:
        raise OriginInvalid(_("The address is too long."))
    return origin


def set_origin(link: RunTestLink, value: str, *, admin_id: str) -> None:
    """Only how this link is shown and copied; the audit holds neither the address nor the token."""
    authoring.ensure_editable(link.run.quiz)
    origin = clean_origin(value)
    with transaction.atomic():
        link.shown_origin = origin
        link.save(update_fields=["shown_origin"])
        _audit("address_changed", link, admin_id)


def is_playable(link: RunTestLink, now: datetime) -> bool:
    return link.is_playable(now)


def find_playable(token: str) -> RunTestLink | None:
    link = RunTestLink.objects.filter(token=token).select_related("run", "run__quiz").first()
    return link if link is not None and link.is_playable(timezone.now()) else None


def cancel(link: RunTestLink, *, admin_id: str) -> None:
    """Attempts stay, and the admin can still read them."""
    with transaction.atomic():
        QuizRun.all_kinds.filter(pk=link.run_id, status=QuizRun.Status.OPEN).update(
            status=QuizRun.Status.CLOSED, closed_at=timezone.now()
        )
        _audit("cancelled", link, admin_id)
    link.run.refresh_from_db()


def _assets_of(link: RunTestLink) -> list[str]:
    rows = AttemptAnswer.objects.filter(attempt__run=link.run_id, asset_id__isnull=False)
    return list(rows.values_list("asset_id", flat=True))


def delete_attempts(link: RunTestLink, *, admin_id: str) -> list[str]:
    """Returns the photos' asset ids, for the caller to remove once this has been committed."""
    with transaction.atomic():
        assets = _assets_of(link)
        Attempt.objects.filter(run=link.run_id).delete()
        Participant.objects.filter(run=link.run_id).delete()  # after the attempts: protected
        _audit("attempts_deleted", link, admin_id)
    return assets


def delete(link: RunTestLink, *, admin_id: str) -> list[str]:
    """Dependent rows first, as everything here is protected. A published revision stays.

    Returns the photos' asset ids, for the caller to remove once this has been committed.
    """
    with transaction.atomic():
        assets = _assets_of(link)
        run = link.run
        revision_id = run.current_revision_id
        _audit("deleted", link, admin_id)
        Attempt.objects.filter(run=run).delete()
        Participant.objects.filter(run=run).delete()
        RunRevision.objects.filter(run=run).delete()
        link.delete()
        run.delete()
        QuizRevision.all_kinds.filter(pk=revision_id, status=QuizRevision.Status.TEST_COPY).delete()
    return assets

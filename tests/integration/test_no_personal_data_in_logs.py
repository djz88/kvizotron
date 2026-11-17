"""AC-75: no log line holds a participant's name or e-mail, from the start to the admin table."""

import logging

import pytest

from app.domain import authoring
from app.kernel.models import AdminUser, AuditEvent
from tests.api.conftest import PASSWORD
from tests.api.test_identity_flow import Browser, result_url
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
NAMES = ("Tajnajana", "Tajnaeva", "Tajnapetra")
EMAILS = ("tajna.jana@x.cz", "tajna.eva@x.cz", "tajna.petra@x.cz")


@pytest.fixture
def logged_in(client, db):
    client.force_login(AdminUser.objects.create_admin("alice", PASSWORD))
    return client


def capture(caplog):
    """`django.request` does not propagate to root and logs only errors, `app` only warnings."""
    for name in ("", "django", "django.request", "app"):
        caplog.set_level(logging.DEBUG, logger=name)
        if name:
            logging.getLogger(name).addHandler(caplog.handler)


@pytest.fixture(autouse=True)
def detach(caplog):
    yield
    for name in ("django", "django.request", "app"):
        logging.getLogger(name).removeHandler(caplog.handler)


def audit_text():
    return str(list(AuditEvent.objects.values_list("details_json", flat=True)))


def test_no_log_line_contains_name_or_email(caplog, logged_in):
    capture(caplog)
    rules = {"ask_name": "required", "ask_email": "optional", "duplicate_names": "forbid"}
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, rules=rules)
    first = Browser(run)
    first.start()
    assert first.submit(participant_name=NAMES[0], participant_email=EMAILS[0]).status_code == 200
    second = Browser(run)
    second.start()
    refused = second.submit(participant_name=NAMES[0], participant_email=EMAILS[1])
    assert refused.status_code == 409
    # Positive control: the refusal reached a captured logger, so silence below means something.
    assert any(r.name == "django.request" and r.levelno == logging.WARNING for r in caplog.records)
    logging.getLogger("app.test").warning("marker")
    assert "marker" in caplog.text
    assert second.submit(auto_submit="1").status_code == 200
    url = result_url(second)
    FormClient().post(url + "/identity", {"participant_name": NAMES[0]})  # taken: refused
    FormClient().post(
        url + "/identity", {"participant_name": NAMES[1], "participant_email": EMAILS[1]}
    )
    third = Browser(run)
    third.start(participant_name=NAMES[2], participant_email=EMAILS[2])
    page = logged_in.get(f"/admin/runs/{run.id}/attempts?lang=en")
    shown = page.content.decode()
    for value in (NAMES[0], NAMES[1], EMAILS[0], EMAILS[1]):
        assert value in shown  # the table did show them, so the check above means something
    for value in (*NAMES, *EMAILS):
        assert value not in caplog.text
        assert value not in audit_text()

"""AC-161: an admin renames the nickname of a participant."""

import pytest
from django.core.cache import cache

from app.domain import participants, results
from app.domain.models import Participant
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID
from tests.domain.test_identity import a_run, send
from tests.domain.test_results_board import a_run as board_run
from tests.domain.test_results_board import labels, person, played

pytestmark = pytest.mark.django_db


def refused(call):
    with pytest.raises(participants.NameRefused) as caught:
        call()
    return caught.value.code


def test_rename_sets_name_and_key_and_clears_the_scoreboard_cache():
    run = board_run()
    ema = person(run, "Ema")
    played(run, ema, 1)
    cache.clear()
    assert labels(results.board(run, audience="public", locale="cs")) == ["Ema"]
    participants.rename(ema, "  Žába   Ok ", admin_id=ADMIN_ID)
    ema = Participant.objects.get(pk=ema.pk)
    assert (ema.display_name, ema.name_key) == ("Žába Ok", "žába ok")
    assert labels(results.board(run, audience="public", locale="cs")) == ["Žába Ok"]


def test_rename_refuses_empty_too_long_and_taken():
    run = a_run()  # a name is required and equal names are forbidden
    one = send(run, "Ema", "a" * 20)
    send(run, "Jan", "b" * 20)
    assert refused(lambda: participants.rename(one, "   ", admin_id=ADMIN_ID)) == "empty"
    too_long = "x" * (participants.NAME_LENGTH + 1)
    assert refused(lambda: participants.rename(one, too_long, admin_id=ADMIN_ID)) == "too_long"
    assert refused(lambda: participants.rename(one, " jan ", admin_id=ADMIN_ID)) == "taken"
    assert Participant.objects.get(pk=one.pk).display_name == "Ema"
    assert not AuditEvent.objects.filter(action="participant.renamed").exists()
    participants.rename(one, "EMA", admin_id=ADMIN_ID)  # one's own name, another way of writing it
    assert Participant.objects.get(pk=one.pk).display_name == "EMA"


def test_without_the_rule_the_same_name_is_allowed():
    run = a_run(duplicate_names="allow")
    one = send(run, "Ema", "a" * 20)
    send(run, "Jan", "b" * 20)
    participants.rename(one, "Jan", admin_id=ADMIN_ID)
    assert Participant.objects.get(pk=one.pk).display_name == "Jan"


def test_rename_audit_has_no_name():
    run = a_run()
    one = send(run, "Ema", "a" * 20)
    participants.rename(one, "Tajné", admin_id=ADMIN_ID)
    (event,) = AuditEvent.objects.filter(action="participant.renamed")
    assert event.details_json == {}
    assert (event.entity_type, event.entity_id) == ("participant", str(one.pk))
    assert "Tajné" not in str(event.__dict__) and "Ema" not in str(event.__dict__)


def test_rename_leaves_name_dropped_alone():
    run = a_run()
    one = send(run, "Ema", "a" * 20)
    Participant.objects.filter(pk=one.pk).update(name_dropped=True)
    participants.rename(Participant.objects.get(pk=one.pk), "Nové", admin_id=ADMIN_ID)
    assert Participant.objects.get(pk=one.pk).name_dropped is True


def test_the_name_length_is_the_one_of_the_model():
    assert participants.NAME_LENGTH == Participant._meta.get_field("display_name").max_length

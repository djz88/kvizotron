"""The administration pages of deletion: history, held runs, delete now, erasure, the date."""

import logging
import re
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.db.models import ProtectedError
from django.urls import reverse
from django.utils import timezone

from app.domain import authoring, clock, data_policy, heartbeat, participants, retention
from app.domain.models import Participant, QuizRun
from app.kernel import registry
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
EMAIL = "jana@example.test"
THEME_CSS = (
    Path(__file__).resolve().parents[2] / "app/plugins/theme_default/assets/theme.css"
).read_text(encoding="utf-8")
NO_STORE = "no-store"


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


def text(response):
    return response.content.decode()


def open_run(slug="kviz"):
    return authoring.open_run(
        published_quiz(slug, questions=1), admin_id=ADMIN_ID, data={"profile": "answers"}
    )


def ended_run(slug="kviz", *, period="30d", days_ago=1, **fields):
    run = open_run(slug)
    QuizRun.objects.filter(pk=run.pk).update(
        status=QuizRun.Status.CLOSED,
        closed_at=timezone.now() - timedelta(days=days_ago),
        retention_json={"profile": "answers", "period": period},
        **fields,
    )
    run.refresh_from_db()
    return run


def person(run, key="a", name="Jana", email=EMAIL):
    return Participant.objects.create(
        run=run,
        anonymous_key_hash=key,
        display_name=name,
        name_key=registry.get("participant_policy", "basic").name_key(name),
        email=email,
        email_key=participants.email_key_of(email),
    )


def trail():
    return registry.get("retention", "local")


def run_page(run, *, lang="en"):
    return f"/admin/runs/{run.id}?lang={lang}"


def runs_list(run, *, query="archived=1&lang=en"):
    return reverse("admin_run_open", args=[run.quiz_id]) + f"?{query}"


def test_history_lists_each_kind_with_who_when_run_and_counts(logged_in, admin_user):
    """AC-117: an automatic, a manual and an erasure row, each saying who, when, run and counts."""
    automatic = ended_run("samo")
    person(automatic)
    retention.purge_run(automatic, trigger=retention.AUTOMATIC, admin_id=None)
    manual = ended_run("rucni")
    retention.delete_now(manual, admin_id=str(admin_user.pk))
    erased = ended_run("vymaz")
    who = person(erased, "b", name="Petr")
    retention.erase([str(who.pk)], admin_id=str(admin_user.pk))

    html = text(logged_in.get("/admin/retention?lang=en"))

    assert "Automatic" in html and "Manual" in html and "Erasure" in html
    assert "alice" in html and ">automatic<" in html
    for run in (automatic, manual, erased):
        assert f"/admin/runs/{run.id}" in html
    assert "Participants: 1" in html
    assert "Název cs" in html


def test_the_history_holds_no_name_or_address(logged_in, admin_user):
    run = ended_run()
    who = person(run)
    retention.erase([str(who.pk)], admin_id=str(admin_user.pk), email=EMAIL)
    html = text(logged_in.get("/admin/retention?lang=en"))
    assert EMAIL not in html and "Jana" not in html


def test_an_erasure_on_a_test_run_has_no_link_that_would_be_a_404(logged_in, admin_user):
    run = open_run()
    QuizRun.objects.filter(pk=run.pk).update(kind=QuizRun.Kind.TEST, run_no=None)
    who = person(run)
    retention.erase([str(who.pk)], admin_id=str(admin_user.pk))
    html = text(logged_in.get("/admin/retention?lang=en"))
    assert f"/admin/runs/{run.id}" not in html
    assert "Název cs" in html


def test_the_run_page_links_to_its_own_row(logged_in, admin_user):
    """AC-117: the run page links to its own row of the history."""
    run = ended_run()
    retention.delete_now(run, admin_id=str(admin_user.pk))
    assert f"/admin/retention?run={run.id}" in text(logged_in.get(run_page(run)))


def many_records(count):
    """The oldest record is the real run's; the newer ones point at runs that do not exist."""
    run = ended_run()
    trail().record(
        str(run.id),
        trigger="manual",
        admin_id=None,
        policy="30d",
        cutoff_at=None,
        counts={},
    )
    for _ in range(count):
        trail().record(
            str(uuid4()),
            trigger="automatic",
            admin_id=None,
            policy="30d",
            cutoff_at=None,
            counts={},
        )
    return run


def test_the_history_pages_so_older_rows_can_be_reached(logged_in):
    """AC-117: nothing is cut off: past 200 rows the older ones are on the next page."""
    run = many_records(200)
    first = text(logged_in.get("/admin/retention?lang=en"))
    second = text(logged_in.get("/admin/retention?page=2&lang=en"))
    assert f"/admin/runs/{run.id}" not in first
    assert "?page=2" in first
    assert f"/admin/runs/{run.id}" in second
    assert "?page=1" in second and "?page=3" not in second


def test_the_run_filter_finds_a_row_beyond_the_first_page(logged_in):
    """AC-117: the run page's link works whatever the age of the record."""
    run = many_records(200)
    html = text(logged_in.get(f"/admin/retention?run={run.id}&lang=en"))
    assert f"/admin/runs/{run.id}" in html
    assert "?page=" not in html
    assert "All deletions" in html


@pytest.mark.parametrize("value", ["junk", "0", "-1", "3", "9" * 30, "9" * 5000])
def test_an_unusable_page_is_the_first_page(logged_in, value):
    run = many_records(200)
    response = logged_in.get(f"/admin/retention?page={value}&lang=en")
    assert response.status_code == 200
    assert f"/admin/runs/{run.id}" not in text(response)
    assert "?page=2" in text(response)


def test_an_unusable_run_filter_filters_nothing(logged_in):
    many_records(1)
    html = text(logged_in.get("/admin/retention?run=junk&lang=en"))
    assert "All deletions" not in html
    assert html.count("<tr>") == 3  # the header and two rows


def test_verify_answers_yes_with_date_and_admin_and_no_for_another(logged_in, admin_user):
    """AC-117: typing an erased address says when and by whom; another address says no."""
    run = ended_run()
    who = person(run)
    retention.erase([str(who.pk)], admin_id=str(admin_user.pk), email=EMAIL)

    found = logged_in.post("/admin/retention/verify?lang=en", {"email": " JANA@example.test "})
    other = logged_in.post("/admin/retention/verify?lang=en", {"email": "petr@example.test"})

    assert found.status_code == 200
    assert "was erased" in text(found) and "alice" in text(found)
    assert found["Cache-Control"].count(NO_STORE) == 1
    assert "No erasure of this address is recorded" in text(other)
    assert "was erased" not in text(other)
    assert other["Cache-Control"].count(NO_STORE) == 1


def test_verify_needs_an_address_and_a_post(logged_in):
    response = logged_in.post("/admin/retention/verify?lang=en", {"email": "   "})
    assert response.status_code == 200
    assert "Enter an e-mail address" in text(response)
    assert "No erasure of this address" not in text(response)
    assert logged_in.get(f"/admin/retention/verify?email={EMAIL}").status_code == 405


def test_held_runs_are_listed_above_the_history(logged_in):
    """AC-114: held runs come first on the page."""
    run = ended_run(days_ago=60, retention_held_at=timezone.now())
    html = text(logged_in.get("/admin/retention?lang=en"))
    assert f"/admin/runs/{run.id}" in html
    assert html.index("Runs waiting for confirmation") < html.index('id="history"')


def test_held_runs_are_released_only_after_a_confirmation(logged_in, admin_user):
    """AC-114: without confirm=1 it asks; with it the runs go to the next pass."""
    run = ended_run(days_ago=60, retention_held_at=timezone.now())

    asked = logged_in.post("/admin/retention/held?lang=en", {"run": [str(run.id)]})
    run.refresh_from_db()
    assert asked.status_code == 200
    assert "next hourly pass" in text(asked) and "cannot be undone" in text(asked)
    assert 'name="confirm" value="1"' in text(asked)
    assert run.retention_held_at is not None

    done = logged_in.post("/admin/retention/held", {"confirm": "1", "run": [str(run.id)]})
    run.refresh_from_db()
    assert done.status_code == 302
    assert run.retention_held_at is None
    event = AuditEvent.objects.get(action="retention.held_released")
    assert event.actor_id == str(admin_user.pk)
    assert event.details_json == {"run_ids": [str(run.id)], "count": 1}


def test_the_confirmation_form_carries_the_listed_runs(logged_in):
    """AC-114: what the admin saw is what is posted."""
    run = ended_run(days_ago=60, retention_held_at=timezone.now())
    asked = text(logged_in.post("/admin/retention/held?lang=en", {"run": [str(run.id)]}))
    assert f'name="run" value="{run.id}"' in asked
    page_html = text(logged_in.get("/admin/retention?lang=en"))
    assert f'name="run" value="{run.id}"' in page_html


def test_a_run_held_after_the_page_stays_held(logged_in):
    """AC-114: a run not on the posted list is not released."""
    seen = ended_run("videny", days_ago=60, retention_held_at=timezone.now())
    later = ended_run("pozdejsi", days_ago=60, retention_held_at=timezone.now())
    logged_in.post("/admin/retention/held", {"confirm": "1", "run": [str(seen.id)]})
    seen.refresh_from_db()
    later.refresh_from_db()
    assert seen.retention_held_at is None
    assert later.retention_held_at is not None


@pytest.mark.parametrize("posted", [["junk"], ["", "x"]])
def test_a_malformed_run_id_is_a_form_message(logged_in, posted):
    run = ended_run(days_ago=60, retention_held_at=timezone.now())
    response = logged_in.post(
        "/admin/retention/held?lang=en", {"confirm": "1", "run": [str(run.id), *posted]}
    )
    run.refresh_from_db()
    assert response.status_code == 200
    assert run.retention_held_at is not None
    assert not AuditEvent.objects.filter(action="retention.held_released").exists()


def test_an_empty_confirmation_changes_nothing(logged_in):
    run = ended_run(days_ago=60, retention_held_at=timezone.now())
    response = logged_in.post("/admin/retention/held", {"confirm": "1"})
    run.refresh_from_db()
    assert response.status_code == 302
    assert run.retention_held_at is not None
    assert not AuditEvent.objects.filter(action="retention.held_released").exists()


def test_held_and_delete_data_only_take_a_post(logged_in):
    run = ended_run(days_ago=60, retention_held_at=timezone.now())
    assert logged_in.get("/admin/retention/held").status_code == 405
    assert logged_in.get(f"/admin/runs/{run.id}/delete-data").status_code == 405
    run.refresh_from_db()
    assert run.retention_held_at is not None and run.data_deleted_at is None


def test_with_no_held_run_there_is_nothing_to_ask(logged_in):
    response = logged_in.post("/admin/retention/held")
    assert response.status_code == 302
    assert not AuditEvent.objects.filter(action="retention.held_released").exists()


def test_a_period_that_makes_the_run_due_asks_first(logged_in):
    """AC-114: the period form shows the confirmation page naming the consequence."""
    run = ended_run(period="1y", days_ago=60)
    url = f"/admin/runs/{run.id}/period?lang=en"

    asked = logged_in.post(url, {"retention_period": "30d"})
    run.refresh_from_db()
    assert asked.status_code == 200
    assert "next hourly pass" in text(asked)
    assert 'name="retention_period" value="30d"' in text(asked)
    assert f'href="/admin/runs/{run.id}"' in text(asked)
    assert run.retention_json["period"] == "1y"

    done = logged_in.post(url, {"retention_period": "30d", "confirm": "1"})
    run.refresh_from_db()
    assert done.status_code == 302
    assert run.retention_json["period"] == "30d"


def test_delete_data_asks_then_deletes(logged_in):
    """AC-115: without confirm=1 the page names what goes; with it the data are deleted."""
    run = ended_run()
    person(run)
    url = f"/admin/runs/{run.id}/delete-data?lang=en"

    asked = logged_in.post(url)
    run.refresh_from_db()
    assert asked.status_code == 200
    for word in (
        "attempts",
        "answers",
        "photos",
        "participants",
        "export files",
        "all runs of the quiz",
        "The run itself, its revisions, reward rules, draw history with pseudonyms",
        "cannot be undone",
    ):
        assert word in text(asked)
    assert "Only anonymous" not in text(asked)
    assert run.data_deleted_at is None
    assert Participant.objects.filter(run=run).exists()

    done = logged_in.post(url, {"confirm": "1"})
    run.refresh_from_db()
    assert done.status_code == 302
    assert run.data_deleted_at is not None
    assert not Participant.objects.filter(run=run).exists()


def test_the_button_is_offered_only_where_it_can_work(logged_in, admin_user):
    action = "delete-data"
    assert action not in text(logged_in.get(run_page(open_run("bezi"))))
    ended = ended_run("skoncil")
    assert action in text(logged_in.get(run_page(ended)))
    retention.delete_now(ended, admin_id=str(admin_user.pk))
    assert action not in text(logged_in.get(run_page(ended)))


@pytest.mark.parametrize("sent", [{}, {"confirm": "1"}], ids=["unconfirmed", "confirmed"])
def test_delete_data_is_refused_on_a_run_that_has_not_ended(logged_in, sent):
    """AC-115: a running run keeps its data and the page says why."""
    run = open_run()
    person(run)
    response = logged_in.post(f"/admin/runs/{run.id}/delete-data?lang=en", sent)
    run.refresh_from_db()
    assert response.status_code == 200
    assert "after the run has ended" in text(response)
    assert run.data_deleted_at is None
    assert Participant.objects.filter(run=run).exists()


def test_delete_data_is_refused_on_a_scheduled_run(logged_in):
    """AC-115: a run that has not begun keeps its data, and the page says why."""
    run = open_run()
    person(run)
    QuizRun.objects.filter(pk=run.pk).update(status=QuizRun.Status.SCHEDULED)
    response = logged_in.post(f"/admin/runs/{run.id}/delete-data?lang=en", {"confirm": "1"})
    run.refresh_from_db()
    assert response.status_code == 200
    assert "after the run has ended" in text(response)
    assert run.data_deleted_at is None
    assert Participant.objects.filter(run=run).exists()
    assert not trail().for_run(str(run.id))


def test_delete_data_of_a_test_run_is_404(logged_in):
    run = ended_run()
    QuizRun.objects.filter(pk=run.pk).update(kind=QuizRun.Kind.TEST, run_no=None)
    assert logged_in.post(f"/admin/runs/{run.id}/delete-data").status_code == 404


def test_delete_data_that_fails_shows_a_message(logged_in, monkeypatch):
    run = ended_run()

    def fails(*args, **kwargs):
        raise OSError("disk")

    monkeypatch.setattr(retention, "delete_now", fails)
    response = logged_in.post(f"/admin/runs/{run.id}/delete-data?lang=en", {"confirm": "1"})
    assert response.status_code == 200
    assert "could not be finished" in text(response)


def test_delete_data_with_a_protected_row_says_it_can_be_repeated(logged_in, monkeypatch, caplog):
    """AC-116: any failure is the same message, and the log holds the type only."""
    run = ended_run()

    def fails(*args, **kwargs):
        raise ProtectedError("junk@example.test", set())

    monkeypatch.setattr(retention, "delete_now", fails)
    with caplog.at_level(logging.ERROR):
        response = logged_in.post(f"/admin/runs/{run.id}/delete-data?lang=en", {"confirm": "1"})
    assert response.status_code == 200
    assert "could not be finished" in text(response)
    assert "ProtectedError" in caplog.text
    assert "junk@example.test" not in caplog.text


def test_delete_data_again_on_a_stale_page_changes_nothing(logged_in, admin_user):
    run = ended_run()
    retention.delete_now(run, admin_id=str(admin_user.pk))
    response = logged_in.post(f"/admin/runs/{run.id}/delete-data", {"confirm": "1"})
    assert response.status_code == 302
    assert len(trail().for_run(str(run.id))) == 1


def _keeps_the_referrer_for_csrf(response):
    assert response.status_code == 200
    assert NO_STORE in response["Cache-Control"]
    assert response.get("Referrer-Policy") != "no-referrer"


def test_the_pages_with_forms_are_not_cached_and_keep_the_referrer(logged_in):
    """AC-116: over HTTPS a form posted with no Referer is refused by the CSRF check."""
    who = person(ended_run())
    url = "/admin/retention/erasure?lang=en"
    for response in (
        logged_in.get(url),
        logged_in.post(url, {"action": "search", "email": EMAIL}),
        logged_in.post(url, {"action": "erase", "email": EMAIL, "participant": [str(who.pk)]}),
        logged_in.post("/admin/retention/verify?lang=en", {"email": EMAIL}),
    ):
        _keeps_the_referrer_for_csrf(response)


def test_the_erasure_search_passes_a_real_csrf_check(admin_user):
    """AC-116: the form's token and the page's Referer are accepted; no Referer is refused."""
    person(ended_run())
    browser = FormClient(enforce_csrf_checks=True)
    browser.force_login(admin_user)
    address = "/admin/retention/erasure"
    form = text(browser.get(address, secure=True))
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', form).group(1)
    sent = {"csrfmiddlewaretoken": token, "action": "search", "email": EMAIL}

    with_referer = browser.post(
        address, sent, secure=True, HTTP_REFERER=f"https://testserver{address}"
    )
    without = browser.post(address, sent, secure=True)

    assert with_referer.status_code == 200
    assert EMAIL in text(with_referer)
    assert without.status_code == 403


def test_the_pager_leads_to_the_history_from_the_verify_page(logged_in):
    many_records(200)
    html = text(logged_in.post("/admin/retention/verify?lang=en", {"email": EMAIL}))
    assert 'href="/admin/retention?page=2"' in html


def test_an_erasure_search_shows_rows_that_are_not_cached(logged_in):
    """AC-116: quiz, run, nickname and e-mail, in a response with no-store."""
    run = ended_run()
    person(run)
    response = logged_in.post(
        "/admin/retention/erasure?lang=en", {"action": "search", "email": " JANA@example.test"}
    )
    html = text(response)
    assert response.status_code == 200
    assert response["Cache-Control"].count(NO_STORE) == 1
    assert "Název cs" in html and "Jana" in html and EMAIL in html


def test_an_erasure_search_by_nickname(logged_in):
    """AC-116: a nickname search compares the name key."""
    person(ended_run(), email=None)
    response = logged_in.post(
        "/admin/retention/erasure?lang=en", {"action": "search", "name": " JANA "}
    )
    assert "Jana" in text(response)
    assert response["Cache-Control"].count(NO_STORE) == 1


def test_an_address_in_the_query_string_is_not_searched(logged_in):
    """AC-116: the address only ever comes from a POST body."""
    person(ended_run())
    response = logged_in.get(f"/admin/retention/erasure?lang=en&email={EMAIL}")
    assert response.status_code == 200
    assert EMAIL not in text(response)


def test_an_empty_search_asks_for_something(logged_in):
    response = logged_in.post("/admin/retention/erasure?lang=en", {"action": "search"})
    assert "Enter an e-mail address or a nickname" in text(response)


def test_erasure_deletes_only_the_ticked_rows_after_a_confirmation(logged_in, admin_user):
    """AC-116: the confirmation names the chosen rows and only they are deleted."""
    run = ended_run()
    chosen = person(run, "a")
    left = person(run, "b")
    url = "/admin/retention/erasure?lang=en"
    sent = {"action": "erase", "email": EMAIL, "participant": [str(chosen.pk)]}

    asked = logged_in.post(url, sent)
    assert asked.status_code == 200
    assert asked["Cache-Control"].count(NO_STORE) == 1
    for word in (
        "export files",
        "all runs of a quiz",
        "other participants stay",
        "draw history keeps only a pseudonym",
        "cannot be undone",
    ):
        assert word in text(asked)
    assert "The rest of each run" not in text(asked)
    assert 'name="confirm" value="1"' in text(asked)
    assert str(left.pk) not in text(asked)
    assert Participant.objects.filter(pk=chosen.pk).exists()

    done = logged_in.post(url, sent | {"confirm": "1"})
    assert done.status_code == 302
    assert EMAIL not in done["Location"]
    assert not Participant.objects.filter(pk=chosen.pk).exists()
    assert Participant.objects.filter(pk=left.pk).exists()
    assert trail().for_run(str(run.id))[0].has_fingerprint


def test_an_erasure_by_nickname_stores_no_fingerprint(logged_in):
    run = ended_run()
    who = person(run, email=None)
    logged_in.post(
        "/admin/retention/erasure",
        {"action": "erase", "name": "Jana", "participant": [str(who.pk)], "confirm": "1"},
    )
    assert not trail().for_run(str(run.id))[0].has_fingerprint


def test_a_row_the_search_does_not_find_is_not_erased(logged_in):
    """A forged id cannot put the fingerprint of one address on another person."""
    run = ended_run()
    outsider = person(run, "b", name="Petr", email="petr@example.test")
    response = logged_in.post(
        "/admin/retention/erasure?lang=en",
        {"action": "erase", "email": EMAIL, "participant": [str(outsider.pk)], "confirm": "1"},
    )
    assert response.status_code == 200
    assert "Select at least one row" in text(response)
    assert Participant.objects.filter(pk=outsider.pk).exists()


@pytest.mark.parametrize("confirm", [{}, {"confirm": "1"}], ids=["unconfirmed", "confirmed"])
def test_a_malformed_id_is_a_form_error(logged_in, confirm):
    """AC-116: never a 500, and nothing is deleted."""
    who = person(ended_run())
    response = logged_in.post(
        "/admin/retention/erasure?lang=en",
        {"action": "erase", "email": EMAIL, "participant": [str(who.pk), "junk"]} | confirm,
    )
    assert response.status_code == 200
    assert "Select at least one row" in text(response)
    assert response["Cache-Control"].count(NO_STORE) == 1
    assert Participant.objects.filter(pk=who.pk).exists()


def test_an_erasure_with_no_row_ticked_is_a_form_error(logged_in):
    person(ended_run())
    response = logged_in.post(
        "/admin/retention/erasure?lang=en", {"action": "erase", "email": EMAIL}
    )
    assert "Select at least one row" in text(response)


def test_an_erasure_with_a_protected_row_says_it_can_be_repeated(logged_in, monkeypatch, caplog):
    """AC-116: any failure is the same message, and the log holds the type only."""
    who = person(ended_run())

    def fails(*args, **kwargs):
        raise ProtectedError("junk@example.test", set())

    monkeypatch.setattr(retention, "erase", fails)
    with caplog.at_level(logging.ERROR):
        response = logged_in.post(
            "/admin/retention/erasure?lang=en",
            {"action": "erase", "email": EMAIL, "participant": [str(who.pk)], "confirm": "1"},
        )
    assert response.status_code == 200
    assert "incomplete" in text(response) and "repeat" in text(response)
    assert "ProtectedError" in caplog.text
    assert "junk@example.test" not in caplog.text


def test_an_erasure_that_fails_says_it_is_incomplete_and_can_be_repeated(logged_in, monkeypatch):
    """AC-116: an export that cannot be removed: the rest stays and the rows are offered again."""
    run = ended_run()
    who = person(run)

    def fails(*args, **kwargs):
        raise OSError("disk")

    monkeypatch.setattr(retention, "erase", fails)
    response = logged_in.post(
        "/admin/retention/erasure?lang=en",
        {"action": "erase", "email": EMAIL, "participant": [str(who.pk)], "confirm": "1"},
    )
    assert response.status_code == 200
    assert "incomplete" in text(response) and "repeat" in text(response)
    assert response["Cache-Control"].count(NO_STORE) == 1
    assert str(who.pk) in text(response)


def test_the_date_shows_and_warns_only_near_the_end(logged_in):
    """AC-118: at 9 days left the date is marked and says 9; at 30 days it is not marked."""
    near = ended_run("blizko", days_ago=21)
    far = ended_run("daleko", period="1y", days_ago=1)

    near_html = text(logged_in.get(run_page(near)))
    assert 'class="deletion-soon"' in near_html
    assert "Days left: 9" in near_html
    list_html = text(logged_in.get(runs_list(near)))
    assert 'class="deletion-soon"' in list_html
    assert "Days left: 9" in list_html

    far_html = text(logged_in.get(run_page(far)))
    assert "Data will be deleted" in far_html
    assert "deletion-soon" not in far_html
    far_list = text(logged_in.get(runs_list(far)))
    assert clock.shown(data_policy.deletion_at(far)) in far_list
    assert "deletion-soon" not in far_list


def test_the_column_of_the_list_holds_only_the_essentials(logged_in):
    """AC-118: the heading says what it is, so a cell has no sentence and no second link."""
    near = ended_run("blizko", days_ago=21)
    held = ended_run("drzeny", days_ago=60, retention_held_at=timezone.now())

    near_list = text(logged_in.get(runs_list(near)))
    held_list = text(logged_in.get(runs_list(held)))

    assert "Data will be deleted" not in near_list
    assert 'class="deletion-soon"' in near_list and "Days left: 9" in near_list
    assert "Waits for confirmation" in held_list
    assert "Deletion waits for confirmation" not in held_list
    assert held_list.count('href="/admin/retention"') == 1  # the menu only


def test_the_date_is_in_the_status_cell_and_the_table_keeps_its_columns(logged_in):
    """AC-118: a date in a column of its own was hidden behind scrolling at 1280 px."""
    html = text(logged_in.get(runs_list(ended_run(days_ago=21))))
    cell = re.search(r'<td data-label="Status">(.*?)</td>', html, re.S).group(1)
    assert 'class="deletion-soon"' in cell and "Days left: 9" in cell
    assert "Deletion of data" not in html
    assert "overflow-auto" not in html


def test_the_status_and_the_date_are_one_item_in_the_phone_layout(logged_in):
    """A stacked cell is a flex row: without one wrapper they would sit side by side."""
    html = text(logged_in.get(runs_list(ended_run(days_ago=21))))
    cell = re.search(r'<td data-label="Status">(.*?)</td>', html, re.S).group(1)
    assert cell.startswith("<div>") and cell.endswith("</div>")
    assert "<br>" in cell


def test_the_marked_date_wraps_as_one_block():
    block = re.search(r"\.deletion-soon \{(.*?)\}", THEME_CSS, re.S).group(1)
    assert "display: inline-block" in block
    assert "max-width: 100%" in block
    assert "white-space: normal" in block


def test_the_date_says_in_czech_how_many_days_are_left(logged_in):
    """AC-118: the words carry the meaning, not only the colour."""
    html = text(logged_in.get(run_page(ended_run(days_ago=21), lang="cs")))
    assert "Zbývá dní: 9" in html


def test_a_run_with_no_date_shows_none(logged_in):
    for run in (open_run("bezi"), ended_run("navzdy", period="permanent")):
        assert "Data will be deleted" not in text(logged_in.get(run_page(run)))


def test_a_held_run_says_it_waits_and_not_in_zero_days(logged_in):
    """AC-118: a held run will not be deleted on that date, so it is not shown as soon."""
    run = ended_run(days_ago=60, retention_held_at=timezone.now())
    for html in (text(logged_in.get(run_page(run))), text(logged_in.get(runs_list(run)))):
        assert "aits for confirmation" in html
        assert "deletion-soon" not in html
        assert "Days left: 0" not in html


def test_a_run_past_its_date_says_the_next_pass_and_not_zero_days(logged_in):
    run = ended_run(days_ago=60)
    html = text(logged_in.get(run_page(run)))
    assert "next hourly pass" in html
    assert 'class="deletion-soon"' in html
    assert "Days left: 0" not in html


def test_a_deleted_run_shows_the_label_and_no_period_form(showing_all, admin_user):
    """AC-118: the label with the date, the summary statistics and no period form."""
    run = ended_run()
    retention.delete_now(run, admin_id=str(admin_user.pk))
    for html in (text(showing_all.get(run_page(run))), text(showing_all.get(runs_list(run)))):
        assert "Data deleted" in html
        assert "deletion-soon" not in html
    page = text(showing_all.get(run_page(run)))
    assert "Submitted attempts" in page
    assert f"/admin/runs/{run.id}/period" not in page


def test_a_deleted_run_says_so_in_czech(logged_in, admin_user):
    run = ended_run()
    retention.delete_now(run, admin_id=str(admin_user.pk))
    assert "Data smazána" in text(logged_in.get(run_page(run, lang="cs")))


def test_the_menu_leads_to_the_history(logged_in):
    assert 'href="/admin/retention"' in text(logged_in.get("/admin/quizzes?lang=en"))
    assert "Deletion history" in text(logged_in.get("/admin/quizzes?lang=en"))


@pytest.fixture
def pass_folder(settings, monkeypatch, tmp_path):
    monkeypatch.setitem(settings.DATABASES["default"], "NAME", str(tmp_path / "db.sqlite3"))
    return tmp_path


@pytest.mark.parametrize(
    ("lang", "outcome", "line"),
    [
        ("en", "ok", "Last pass: {when}, ok"),
        ("en", "failed", "Last pass: {when}, failed"),
        ("cs", "ok", "Poslední průchod: {when}, v pořádku"),
        ("cs", "failed", "Poslední průchod: {when}, selhal"),
        ("en", "stopped", "Last pass: {when}, stopped"),
        ("cs", "stopped", "Poslední průchod: {when}, přerušen"),
    ],
)
def test_the_history_shows_when_the_last_pass_finished_and_how(
    logged_in, pass_folder, lang, outcome, line
):
    """AC-144: the line names the finish in the configured zone and the outcome."""
    finished = timezone.now() - timedelta(minutes=5)
    heartbeat.write_pass(finished - timedelta(seconds=3), finished, outcome, pass_folder)

    html = text(logged_in.get(f"/admin/retention?lang={lang}"))

    assert line.format(when=clock.shown(finished)) in html


def test_the_history_says_when_no_pass_has_finished_yet(logged_in, pass_folder):
    """AC-144: a record of a pass that only started says so."""
    heartbeat.write_pass(timezone.now(), None, None, pass_folder)

    assert "No pass has finished yet" in text(logged_in.get("/admin/retention?lang=en"))
    assert "Zatím žádný průchod neskončil" in text(logged_in.get("/admin/retention?lang=cs"))


def test_the_history_shows_no_pass_line_without_a_record(logged_in, pass_folder):
    """AC-144: no record file (jobs in another setup) is not an alarm."""
    html = text(logged_in.get("/admin/retention?lang=en"))

    assert "Last pass" not in html and "No pass has finished yet" not in html

"""Times are stored in UTC and read and shown in the one configured zone (FR-10)."""

from datetime import UTC, datetime

import pytest

from app.domain import clock, settings

pytestmark = pytest.mark.django_db


def test_a_time_is_read_in_the_configured_zone():
    assert clock.parse_local("2026-11-12T18:00") == datetime(2026, 11, 12, 17, 0, tzinfo=UTC)


def test_another_zone_changes_the_reading():
    settings.set_global(settings.TIME_ZONE, "Asia/Tokyo", admin_id=None)
    assert clock.parse_local("2026-11-12T18:00") == datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


def test_a_time_skipped_by_the_clock_change_is_refused():
    with pytest.raises(ValueError):
        clock.parse_local("2027-03-28T02:30")


def test_an_ambiguous_time_takes_the_first_occurrence():
    assert clock.parse_local("2026-10-25T02:30") == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)


def test_rubbish_is_refused():
    with pytest.raises(ValueError):
        clock.parse_local("tomorrow")


def test_a_time_carrying_its_own_offset_is_refused():
    with pytest.raises(ValueError):
        clock.parse_local("2026-11-12T18:00+05:00")


def test_a_shown_time_names_the_zone():
    assert clock.shown(datetime(2026, 11, 12, 17, 0, tzinfo=UTC)) == "2026-11-12 18:00 CET"


def test_no_time_shows_a_dash():
    assert clock.shown(None) == "–"


def test_form_value_is_what_a_form_field_expects():
    assert clock.form_value(datetime(2026, 11, 12, 17, 0, tzinfo=UTC)) == "2026-11-12T18:00"
    assert clock.form_value(None) == ""


def test_whole_second_drops_the_fraction():
    moment = datetime(2026, 11, 12, 10, 0, 0, 900000, tzinfo=UTC)
    assert clock.whole_second(moment) == datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def test_time_zone_is_only_global():
    assert settings.TIME_ZONE in settings.keys_for("global")
    assert settings.TIME_ZONE not in settings.keys_for("quiz")
    assert settings.resolve(settings.TIME_ZONE) == "Europe/Prague"


def test_a_zone_outside_the_list_is_refused():
    with pytest.raises(settings.InvalidSettingValue):
        settings.set_global(settings.TIME_ZONE, "Mars/Olympus", admin_id=None)


def test_server_clock_says_time_zone_and_utc():
    found = clock.server_clock()
    assert found["zone"] == "Europe/Prague"
    assert set(found) == {"epoch", "text", "zone", "utc", "server_zone", "server_text"}
    assert "UTC" in found["utc"]


def test_server_clock_names_the_zone_the_server_runs_in(monkeypatch):
    import time

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        panel = clock.server_clock()
        assert panel["server_zone"] == "America/New_York"
        assert panel["server_text"].endswith(("EST", "EDT"))
        assert panel["zone"] == "Europe/Prague"
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_server_clock_without_tz_names_utc(monkeypatch):
    import time

    monkeypatch.delenv("TZ", raising=False)
    time.tzset()
    panel = clock.server_clock()
    assert panel["server_zone"]

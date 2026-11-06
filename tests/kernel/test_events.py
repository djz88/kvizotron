import logging

import pytest
from django.db import transaction

from app.kernel import events
from app.kernel.models import PluginInstallation


@pytest.fixture(autouse=True)
def clean_handlers(monkeypatch):
    monkeypatch.setattr(events, "_handlers", {})


def test_events_match_documented_list():
    assert events.EVENTS == {
        "quiz.published",
        "run.opened",
        "attempt.submitted",
        "run.closed",
        "draw.completed",
        "retention.executed",
    }


def test_unknown_event_rejected_on_subscribe():
    with pytest.raises(ValueError, match="quiz.deleted"):
        events.subscribe("quiz.deleted", lambda payload: None, owner="mod.a")


def test_unknown_event_rejected_on_emit():
    with pytest.raises(ValueError, match="quiz.deleted"):
        events.emit("quiz.deleted", {})


def test_handlers_run_in_subscription_order_after_commit(transactional_db):
    calls = []
    events.subscribe("run.opened", lambda p: calls.append(("first", p["run"])), owner="mod.a")
    events.subscribe("run.opened", lambda p: calls.append(("second", p["run"])), owner="mod.b")
    with transaction.atomic():
        events.emit("run.opened", {"run": 1})
        assert calls == []
    assert calls == [("first", 1), ("second", 1)]


def test_other_events_do_not_reach_handler(transactional_db):
    calls = []
    events.subscribe("run.opened", calls.append, owner="mod.a")
    events.emit("run.closed", {})
    assert calls == []


def test_rollback_emits_nothing(transactional_db):
    calls = []
    events.subscribe("run.opened", calls.append, owner="mod.a")
    with pytest.raises(RuntimeError), transaction.atomic():
        events.emit("run.opened", {})
        raise RuntimeError("rollback")
    assert calls == []


def failing(payload):
    raise RuntimeError("secret detail person@example.org")


def test_failing_handler_does_not_reach_caller_and_others_still_run(transactional_db):
    calls = []
    events.subscribe("attempt.submitted", failing, owner="mod.bad")
    events.subscribe("attempt.submitted", calls.append, owner="mod.good")
    events.emit("attempt.submitted", {"attempt": 1})
    assert calls == [{"attempt": 1}]


def test_failure_log_has_event_module_and_type_but_no_payload(transactional_db, caplog):
    events.subscribe("attempt.submitted", failing, owner="mod.bad")
    with caplog.at_level(logging.ERROR, logger="app.kernel.events"):
        events.emit("attempt.submitted", {"email": "person@example.org"})
    assert "attempt.submitted" in caplog.text
    assert "mod.bad" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "person@example.org" not in caplog.text
    assert "secret detail" not in caplog.text


def test_disabled_module_handler_is_skipped(transactional_db):
    PluginInstallation.objects.create(
        plugin_id="mod.off", version="1", manifest_json={}, enabled=False
    )
    calls = []
    events.subscribe("run.closed", calls.append, owner="mod.off")
    events.emit("run.closed", {})
    assert calls == []

"""Pass mark, attempt limit and after-pass: catalogue, scopes and copy onto the run."""

import pytest

from app.contracts import (
    AFTER_PASS,
    MAX_ATTEMPTS,
    OFFICIAL_ATTEMPT,
    PARTICIPANT_KEYS,
    PASS_MARK,
    RESULT_DISPLAY_KEYS,
    RESULT_KEYS,
)
from app.domain import authoring, participants, results, settings
from app.domain.models import QuizRun
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db


def test_new_keys_resolve_to_defaults():
    quiz = published_quiz()
    assert settings.resolve(PASS_MARK, quiz) == "0"
    assert settings.resolve(MAX_ATTEMPTS, quiz) == "0"
    assert settings.resolve(AFTER_PASS, quiz) == "more"


def test_the_scope_is_global_and_quiz():
    for key in (PASS_MARK, MAX_ATTEMPTS, AFTER_PASS):
        assert settings.CATALOGUE[key].scopes == settings.QUIZ_WIDE


def test_the_choices():
    cat = settings.CATALOGUE
    assert cat[PASS_MARK].choices == tuple(str(n) for n in range(101))
    assert cat[MAX_ATTEMPTS].choices == tuple(str(n) for n in range(21))
    assert cat[AFTER_PASS].choices == ("more", "stop")
    assert cat[OFFICIAL_ATTEMPT].choices == ("best", "first", "last", "average")
    assert "after_close" in cat[settings.REVEAL_MOMENT].choices
    assert PASS_MARK in RESULT_KEYS and PASS_MARK not in RESULT_DISPLAY_KEYS
    assert MAX_ATTEMPTS in PARTICIPANT_KEYS and AFTER_PASS in PARTICIPANT_KEYS


def test_the_run_copies_the_new_keys():
    """AC-172, AC-173: the run copies the pass mark and the attempt rules."""
    quiz = published_quiz()
    settings.set_override(PASS_MARK, quiz, "70", admin_id=ADMIN_ID)
    settings.set_override(MAX_ATTEMPTS, quiz, "2", admin_id=ADMIN_ID)
    run = authoring.open_run(
        quiz,
        admin_id=ADMIN_ID,
        rules={AFTER_PASS: "stop"},
        results={OFFICIAL_ATTEMPT: "average"},
    )
    assert results.of(run)[PASS_MARK] == "70"
    assert results.of(run)[OFFICIAL_ATTEMPT] == "average"
    assert participants.rules_of(run)[MAX_ATTEMPTS] == "2"
    assert participants.rules_of(run)[AFTER_PASS] == "stop"


def test_a_run_without_the_new_keys_reads_defaults():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    QuizRun.objects.filter(pk=run.pk).update(results_json={}, participant_rules_json={})
    run.refresh_from_db()
    assert results.of(run)[PASS_MARK] == "0"
    assert participants.rules_of(run)[MAX_ATTEMPTS] == "0"
    assert participants.rules_of(run)[AFTER_PASS] == "more"


def test_an_open_run_keeps_its_values_when_the_quiz_changes():
    quiz = published_quiz()
    settings.set_override(PASS_MARK, quiz, "70", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    settings.set_override(PASS_MARK, quiz, "50", admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert results.of(run)[PASS_MARK] == "70"

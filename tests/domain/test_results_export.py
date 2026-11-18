"""What a run exports, file by file, under its data profile (AC-101 to AC-108)."""

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.contracts import OFFICIAL_ATTEMPT, REVISION_MODE, REWARD_SOURCE
from app.domain import (
    attempts,
    authoring,
    draws,
    results,
    results_export,
    rewards,
    run_links,
    settings,
)
from app.domain.models import Attempt, Participant, QuizRun
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, OPTION_A, OPTION_B, add_question, make_quiz
from tests.support.clock import freeze
from tests.support.graded import add_graded

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
LEFT, RIGHT = "cccc3333", "dddd4444"
LEFT_MATCH, RIGHT_MATCH = "eeee5555", "ffff6666"


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def matching_config():
    return {
        "prompt": {"cs": "Spojte"},
        "mode": "pairs",
        "items": [
            {
                "id": LEFT,
                "match_id": LEFT_MATCH,
                "text": {"cs": "Praha"},
                "match": {"cs": "Vltava"},
            },
            {
                "id": RIGHT,
                "match_id": RIGHT_MATCH,
                "text": {"cs": "Brno"},
                "match": {"cs": "Svratka"},
            },
        ],
    }


def number_config():
    return {
        "prompt": {"cs": "Kolik?"},
        "value": "10",
        "tolerance": "0",
        "tolerance_kind": "absolute",
    }


def three_types(slug="tri", profile="answers"):
    quiz = make_quiz(slug)
    add_question(quiz)
    authoring.save_question(quiz, None, "number", number_config())
    authoring.save_question(quiz, None, "matching", matching_config())
    settings.set_override(settings.DATA_PROFILE, quiz, profile, admin_id=ADMIN_ID)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return quiz


def a_run(quiz):
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def play(run, number, *, name="", email="", submit=True, who=None):
    who = who or Participant.objects.create(
        run=run,
        anonymous_key_hash=f"h{number}",
        display_name=name,
        email=email or None,
    )
    started = attempts.start(run, participant=who)
    by_type = {q["type"]: q["id"] for q in attempts.questions_of(started.attempt)}
    answers = {
        by_type["choice"]: {"options": [OPTION_A]},
        by_type["number"]: {"value": "12,5"},
        by_type["matching"]: {f"pair_{LEFT}": LEFT_MATCH, f"pair_{RIGHT}": RIGHT_MATCH},
    }
    if submit:
        attempts.submit(started.attempt.id, started.token, answers, f"k-{number:012d}")
    return Attempt.objects.get(pk=started.attempt.id)


def table(found, name):
    return next(item for item in found if item.name == name)


def test_offered_follows_profile():
    """AC-101."""
    none_run = a_run(three_types("nic", profile="none"))
    full_run = a_run(three_types("vse", profile="answers"))
    found = results_export.offered([none_run, full_run])
    assert found["questions"] == 2
    assert found["attempts"] == 1 and found["participants"] == 1 and found["answers"] == 1
    assert results_export.offered([none_run]) == {"questions": 1}


def test_none_gives_counts_only():
    """AC-101, AC-108: the row still names the run and its revision."""
    run = a_run(three_types(profile="none"))
    QuizRun.objects.filter(pk=run.pk).update(stateless_submitted=4)
    run.refresh_from_db()
    (questions,) = results_export.tables([run], ["questions"], "cs", photos=False)
    assert len(questions.rows) == 1
    row = questions.rows[0]
    revision = str(run.current_revision.revision_no)
    assert (row["run"], row["revision"], row["submitted"]) == ("1", revision, "4")


def test_answers_one_row_per_attempt_question():
    """AC-103."""
    run = a_run(three_types())
    play(run, 1)
    play(run, 2)
    (answers,) = results_export.tables([run], ["answers"], "cs", photos=False)
    assert len(answers.rows) == 6
    shown = {row["question"]: row["answer"] for row in answers.rows}
    assert shown["Otázka cs"] == "Ano cs"
    assert shown["Kolik?"] == "12,5"
    assert "Praha: Vltava" in shown["Spojte"]
    for row in answers.rows:
        for cell in row.values():
            assert "{" not in cell and "correct" not in cell
            assert OPTION_A not in cell and OPTION_B not in cell


def test_unsubmitted_and_test_runs_left_out():
    """AC-103."""
    quiz = three_types()
    run = a_run(quiz)
    play(run, 1)
    play(run, 2, submit=False)
    link = run_links.create(quiz, quiz.revisions.get(), expires_at=None, admin_id=ADMIN_ID)
    play(link.run, 3)
    found = results_export.tables(
        results_export.runs_for(quiz, None), ["attempts", "answers"], "cs", photos=False
    )
    assert len(table(found, "attempts").rows) == 1
    assert len(table(found, "answers").rows) == 3
    assert results_export.runs_for(quiz, None) == [run]


def test_rows_carry_run_and_revision():
    """AC-108."""
    quiz = three_types()
    first = a_run(quiz)
    play(first, 1)
    authoring.close_run(first, admin_id=ADMIN_ID)
    add_question(quiz, OPTION_B)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    second = a_run(quiz)
    play(second, 2)
    found = results_export.tables(
        results_export.runs_for(quiz, None), list(results_export.FILES), "cs", photos=False
    )
    attempts_rows = table(found, "attempts").rows
    assert [(row["run"], row["revision"]) for row in attempts_rows] == [("1", "1"), ("2", "2")]
    for item in found:
        assert list(item.columns[:2]) == ["run", "revision"]
    questions = table(found, "questions").rows
    assert {(row["run"], row["revision"]) for row in questions} == {("1", "1"), ("2", "2")}


def test_numbers_and_times_by_locale():
    run = a_run(three_types())
    attempt = play(run, 1)
    Attempt.objects.filter(pk=attempt.pk).update(score=Decimal("7.5"))
    (cs,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    (en,) = results_export.tables([run], ["attempts"], "en", photos=False)
    assert cs.rows[0]["score"] == "7,5"
    assert en.rows[0]["score"] == "7.5"
    assert "score" in cs.numeric
    assert re.search(r"[+-]\d\d:\d\d$", cs.rows[0]["submitted_at"])


def test_headers_in_admin_language():
    """AC-102."""
    run = a_run(three_types())
    (cs,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    (en,) = results_export.tables([run], ["attempts"], "en", photos=False)
    assert list(cs.columns) == list(en.columns)
    assert list(cs.headers) != list(en.headers)
    assert len(cs.headers) == len(cs.columns)


def test_duration_only_under_detailed():
    detailed = a_run(three_types("podrobne", profile="detailed"))
    answers = a_run(three_types("odpovedi", profile="answers"))
    assert (
        "duration" in results_export.tables([detailed], ["attempts"], "cs", photos=False)[0].columns
    )
    assert (
        "duration"
        not in results_export.tables([answers], ["attempts"], "cs", photos=False)[0].columns
    )


def test_participants_hold_email():
    run = a_run(three_types())
    play(run, 1, name="Jana", email="jana@example.org")
    (people,) = results_export.tables([run], ["participants"], "cs", photos=False)
    assert people.rows[0]["email"] == "jana@example.org"
    assert people.rows[0]["name"] == "Jana"
    assert people.rows[0]["attempts"] == "1"


def test_audit_has_no_personal_values():
    """AC-107."""
    quiz = three_types()
    run = a_run(quiz)
    play(run, 1, name="Jana", email="jana@example.org")
    choices = {
        "quiz": str(quiz.id),
        "runs": [str(run.id)],
        "files": ["attempts", "participants"],
        "photos": False,
        "name": "tri-run-1",
    }
    results_export.tables([run], list(results_export.FILES), "cs", photos=False)
    results_export.record_created("job-1", ADMIN_ID, choices)
    results_export.record_downloaded("job-1", ADMIN_ID, "participants.csv")
    events = AuditEvent.objects.filter(action__startswith="export.")
    assert {event.action for event in events} == {"export.created", "export.downloaded"}
    created = events.get(action="export.created").details_json
    assert created["personal"] is True and created["runs"] == [str(run.id)]
    for event in events:
        text = str(event.details_json)
        assert "Jana" not in text and "jana@example.org" not in text


def test_foreign_run_refused():
    """AC-108."""
    quiz_a = three_types("a")
    quiz_b = three_types("b")
    own = a_run(quiz_a)
    foreign = a_run(quiz_b)
    link = run_links.create(quiz_a, quiz_a.revisions.get(), expires_at=None, admin_id=ADMIN_ID)
    with pytest.raises(QuizRun.DoesNotExist):
        results_export.runs_for(quiz_a, [str(foreign.id)])
    with pytest.raises(QuizRun.DoesNotExist):
        results_export.runs_for(quiz_a, [str(link.run.id)])
    with pytest.raises(QuizRun.DoesNotExist):
        results_export.runs_for(quiz_a, ["not-a-uuid"])
    assert results_export.runs_for(quiz_a, [str(own.id)]) == [own]


def test_file_name_is_safe():
    quiz = three_types("Můj kvíz")
    run = a_run(quiz)
    at = datetime(2030, 1, 1, 10, 5, tzinfo=UTC)
    single = results_export.file_name(quiz, [run], False, at)
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", single)
    assert single.endswith("-run-1-" + at.astimezone(settings.zone()).strftime("%Y%m%d-%H%M"))
    assert "-all-" in results_export.file_name(quiz, [run], True, at)


def rewarded_run(names):
    quiz = three_types("odmeny")
    draw = rewards.RuleData(
        kind="draw",
        winners=1,
        alternates=1,
        texts={"cs": {"name": "Hlavní cena", "description": "", "claim": ""}},
    )
    rewards.save_rule(quiz, draw, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    run = a_run(quiz)
    for number, name in enumerate(names, start=1):
        play(run, number, name=name, email=f"{name.lower()}@example.org")
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    return run, rewards.rules_of(run)[0]


def test_draws_name_winners_without_email_and_entitlements_hold_it():
    run, rule = rewarded_run(["Jana", "Petr"])
    draws.draw(rule, admin_id=ADMIN_ID)
    assert results_export.offered([run])["draws"] == 1
    found = results_export.tables([run], ["entitlements", "draws"], "cs", photos=False)
    (drawn,) = table(found, "draws").rows
    assert drawn["reward"] == "Hlavní cena" and drawn["draw_no"] == "1"
    assert drawn["eligible"] == "2"
    winner = Participant.objects.get(pk=draws.standing(rule).winners[0].participant_id)
    assert drawn["winners"] == f"{winner.display_name} ({winner.id})"
    assert "@" not in str(drawn)
    (entitled,) = table(found, "entitlements").rows
    assert entitled["email"] == winner.email
    assert entitled["participant_id"] == str(winner.id)


def test_photo_answer_names_its_file(graded_type):
    quiz = make_quiz("foto")
    add_graded(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = a_run(quiz)
    who = Participant.objects.create(run=run, anonymous_key_hash="foto")
    started = attempts.start(run, participant=who)
    question = attempts.questions_of(started.attempt)[0]["id"]
    attempts.submit(started.attempt.id, started.token, {question: {"image": "a" * 32}}, "key-1")
    assert results_export.has_photos([run])
    path = f"photos/1/{started.attempt.id}-1.webp"
    assert results_export.photo_files([run]) == {path: "a" * 32}
    (answers,) = results_export.tables([run], ["answers"], "cs", photos=False)
    assert answers.rows[0]["answer"].endswith(path)
    assert results_export.offered([run])["answers"] == 1


def test_places_while_the_public_board_is_hidden():
    """AC-103."""
    run = a_run(three_types())
    first = play(run, 1, name="Jana")
    second = play(run, 2, name="Petr")
    Attempt.objects.filter(pk=first.pk).update(score=Decimal(1))
    Attempt.objects.filter(pk=second.pk).update(score=Decimal(3))
    (found,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    places = {row["attempt_id"]: (row["place"], row["official"]) for row in found.rows}
    assert places == {str(second.id): ("1", "ano"), str(first.id): ("2", "ano")}


def test_places_per_revision_table():
    """AC-108."""
    quiz = three_types()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, results={REVISION_MODE: "separate"})
    old = play(run, 1, name="Jana")
    add_question(quiz, OPTION_B)
    authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    run.refresh_from_db()
    new = play(run, 2, name="Petr")
    (found,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    places = {row["attempt_id"]: (row["revision"], row["place"]) for row in found.rows}
    assert places == {str(old.id): ("1", "1"), str(new.id): ("2", "1")}


def test_places_by_percent_are_one_table_over_revisions():
    """AC-06, AC-108: the default board ranks both revisions together."""
    quiz = three_types()
    run = a_run(quiz)
    old = play(run, 1, name="Jana")
    add_question(quiz, OPTION_B)
    authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    run.refresh_from_db()
    new = play(run, 2, name="Petr")  # leaves the new question unanswered, so a lower percent
    (found,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    places = {row["attempt_id"]: (row["revision"], row["place"]) for row in found.rows}
    assert places == {str(old.id): ("1", "1"), str(new.id): ("2", "2")}


def test_places_of_a_shared_main_run_stay_within_the_run():
    """AC-177: the export is the run's own data, so a shared board never changes its places."""
    quiz = three_types()
    first = a_run(quiz)
    best = play(first, 1, name="Jana")
    Attempt.objects.filter(pk=best.pk).update(score=Decimal(3))
    authoring.close_run(first, admin_id=ADMIN_ID)
    second = a_run(quiz)
    own = play(second, 2, name="Petr")
    Attempt.objects.filter(pk=own.pk).update(score=Decimal(1))
    results.share_board(second, [first], admin_id=ADMIN_ID)
    assert [
        r.label for r in results.board(second, audience="admin", locale="cs").tables[0].rows
    ] == [
        "Běh 1 · Jana",
        "Běh 2 · Petr",
    ]
    (found,) = results_export.tables([second], ["attempts"], "cs", photos=False)
    assert {row["attempt_id"]: row["place"] for row in found.rows} == {str(own.id): "1"}


def test_official_is_the_attempt_rewards_count():
    """AC-103; TD-047: under `latest` the official attempt is the board's, though not the best."""
    quiz = three_types()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, results={REVISION_MODE: "latest"})
    old = play(run, 1, name="Jana")
    Attempt.objects.filter(pk=old.pk).update(score=Decimal(3))
    add_question(quiz, OPTION_B)
    authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    run.refresh_from_db()
    new = play(run, 2, who=old.participant)
    Attempt.objects.filter(pk=new.pk).update(score=Decimal(1))
    assert results.official_attempt(old.participant).pk == new.pk  # old has more points
    (found,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    shown = {row["attempt_id"]: (row["official"], row["place"]) for row in found.rows}
    assert shown == {str(old.id): ("ne", ""), str(new.id): ("ano", "1")}


def test_export_marks_all_attempts_under_average():
    """ADR-0063: every submitted attempt counts toward an average, so every one is official."""
    quiz = three_types()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, results={OFFICIAL_ATTEMPT: "average"})
    first = play(run, 1, name="Jana")
    second = play(run, 2, who=first.participant)
    (found,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    shown = {row["attempt_id"]: row["official"] for row in found.rows}
    assert shown == {str(first.id): "ano", str(second.id): "ano"}


def test_export_average_under_latest_marks_only_the_current_revision():
    """TD-047: under `latest` the average spans the current revision, as `kept` counts it."""
    quiz = three_types()
    run = authoring.open_run(
        quiz,
        admin_id=ADMIN_ID,
        results={REVISION_MODE: "latest", OFFICIAL_ATTEMPT: "average"},
    )
    old = play(run, 1, name="Jana")
    Attempt.objects.filter(pk=old.pk).update(score=Decimal(8), max_score=Decimal(10))
    add_question(quiz, OPTION_B)
    authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    run.refresh_from_db()
    new = play(run, 2, who=old.participant)
    Attempt.objects.filter(pk=new.pk).update(score=Decimal(9), max_score=Decimal(12))
    assert results.kept(old.participant).count == 1
    (found,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    shown = {row["attempt_id"]: (row["official"], row["place"]) for row in found.rows}
    assert shown == {str(old.id): ("ne", ""), str(new.id): ("ano", "1")}


@pytest.mark.parametrize(("mode", "old_official"), [("percent", "ano"), ("latest", "ne")])
def test_an_attempt_without_a_participant_is_official_only_where_the_mode_counts(
    mode, old_official
):
    """TD-047: an attempt without a browser counts on its own, and only where the mode counts it."""
    quiz = three_types()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, results={REVISION_MODE: mode})
    old = play(run, 1)
    add_question(quiz, OPTION_B)
    authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    run.refresh_from_db()
    new = play(run, 2)
    Attempt.objects.filter(pk__in=[old.pk, new.pk]).update(participant=None)
    (found,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    shown = {row["attempt_id"]: (row["official"], bool(row["place"])) for row in found.rows}
    assert shown == {
        str(old.id): (old_official, old_official == "ano"),
        str(new.id): ("ano", True),
    }


def test_export_marks_only_the_last_under_last():
    quiz = three_types()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, results={OFFICIAL_ATTEMPT: "last"})
    first = play(run, 1, name="Jana")
    second = play(run, 2, who=first.participant)
    (found,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    shown = {row["attempt_id"]: row["official"] for row in found.rows}
    assert shown == {str(first.id): "ne", str(second.id): "ano"}


def test_export_marks_the_submitted_attempt_while_another_waits():
    quiz = three_types()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, results={OFFICIAL_ATTEMPT: "best"})
    first = play(run, 1, name="Jana")
    second = play(run, 2, who=first.participant)
    Attempt.objects.filter(pk=second.pk).update(status=Attempt.Status.PENDING_GRADING)
    (found,) = results_export.tables([run], ["attempts"], "cs", photos=False)
    shown = {row["attempt_id"]: row["official"] for row in found.rows}
    assert shown == {str(first.id): "ano", str(second.id): "ne"}

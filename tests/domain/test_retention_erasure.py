"""Erasing one person across runs: finding them, deleting what they left, and the trail of it."""

import logging
from dataclasses import FrozenInstanceError
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.crypto import salted_hmac

from app.domain import authoring, participants, results, retention, run_links
from app.domain.models import (
    Attempt,
    AttemptAnswer,
    Draw,
    DrawEntry,
    Participant,
    QuizRun,
    RewardEntitlement,
    RewardRule,
)
from app.kernel import registry
from app.kernel.models import AuditEvent
from app.providers.csv_io.models import ExportJobRecord
from app.providers.media_local.models import MediaAsset
from app.providers.retention.models import RetentionJob
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db
ADDRESS = "Jana.Novakova@Example.org"
TYPED = "  jana.NOVAKOVA@example.ORG "
NO_RECORD_YET: list[RetentionJob] = []


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


def a_run(slug="kviz"):
    return authoring.open_run(
        published_quiz(slug, questions=2), admin_id=ADMIN_ID, data={"profile": "answers"}
    )


def a_test_run(slug="zkouska"):
    link = run_links.create(
        published_quiz(slug, questions=2), None, expires_at=None, admin_id=ADMIN_ID
    )
    return link.run


def person(run, key, name="", email=None):
    return Participant.objects.create(
        run=run,
        anonymous_key_hash=key,
        display_name=name,
        name_key=" ".join(name.split()).casefold(),
        email=email,
        email_key=participants.email_key_of(email),
    )


def photo(path):
    asset_id = uuid4()
    MediaAsset.objects.create(
        id=asset_id,
        storage_key=f"{asset_id}.webp",
        mime_type="image/webp",
        size=1,
        sha256="0" * 64,
        private=True,
    )
    (path / f"{asset_id}.webp").write_bytes(b"x")
    return str(asset_id)


def attempt_of(run, who, *, status=Attempt.Status.SUBMITTED, assets=()):
    found = Attempt.objects.create(
        run=run,
        participant=who,
        revision=run.current_revision,
        status=status,
        submitted_at=timezone.now() if status in Attempt.FINISHED else None,
        score=Decimal(1),
        max_score=run.current_revision.max_score,
    )
    for number, asset_id in enumerate(assets):
        AttemptAnswer.objects.create(
            attempt=found,
            question_id=f"q{number}",
            answer_json={},
            auto_points=Decimal(1),
            asset_id=asset_id,
        )
    return found


def entitlement_and_draw_entry(run, who):
    rule = RewardRule.objects.create(quiz=run.quiz, run=run, kind=RewardRule.Kind.DRAW, winners=1)
    RewardEntitlement.objects.create(
        run=run, rule=rule, participant=who, source=RewardEntitlement.Source.DRAW
    )
    draw = Draw.objects.create(
        run=run,
        rule=rule,
        action=Draw.Action.DRAW,
        admin_id=ADMIN_ID,
        eligible_count=2,
        eligible_set_hash="h",
        algorithm="a",
        rules_version="v",
    )
    return DrawEntry.objects.create(
        draw=draw, participant=who, pseudonym="pseudo", position=1, role=DrawEntry.Role.WINNER
    )


def done_export(media_path, run):
    now = timezone.now()
    job = ExportJobRecord.objects.create(
        admin_id="a",
        kind="results",
        status="done",
        choices_json={"quiz": str(run.quiz_id), "runs": [str(run.id)], "all_runs": False},
        report_json={"files": ["x.csv"], "error": None},
        boot="x",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    directory = media_path / "exports" / str(job.pk)
    directory.mkdir(parents=True)
    (directory / "x.csv").write_text("x")
    return job, directory


def ids(*people):
    return [str(who.pk) for who in people]


def records(run):
    return list(RetentionJob.objects.filter(run_id=str(run.pk)))


def test_an_email_search_finds_a_person_across_runs_also_a_test_run():
    """AC-116: another case and spaces around the address do not hide anyone."""
    first, second, trial = a_run("a"), a_run("b"), a_test_run()
    one = person(first, "1", "Jana", ADDRESS)
    two = person(second, "2", "J.", "jana.novakova@example.org")
    three = person(trial, "3", "Zkouška", ADDRESS.upper())
    person(first, "4", "Eva", "eva@example.org")
    person(first, "5", "Beze", None)

    found = retention.search_email(TYPED)

    assert {row.participant_id for row in found} == set(ids(one, two, three))
    by_person = {row.participant_id: row for row in found}
    row = by_person[str(one.pk)]
    assert row.run_id == str(first.pk)
    assert row.quiz_id == str(first.quiz_id)
    assert row.run_no == first.run_no
    assert row.display_name == "Jana"
    assert row.email == ADDRESS
    assert by_person[str(three.pk)].run_no is None
    with pytest.raises(FrozenInstanceError):
        row.email = "x"  # type: ignore[misc]


def test_an_email_search_finds_every_case_of_the_stored_address():
    """AC-146: stored as typed, found by the key, and the rows are the same `Found` rows."""
    run = a_run()
    lower = person(run, "1", "Jana", "a@b.example")
    mixed = person(run, "2", "Eva", "A@B.Example")
    person(run, "3", "Jiná", "other@b.example")

    found = retention.search_email("  A@B.Example ")

    assert {row.participant_id for row in found} == set(ids(lower, mixed))
    assert {row.email for row in found} == {"a@b.example", "A@B.Example"}
    assert all(isinstance(row, retention.Found) for row in found)


def search_queries(count):
    run = a_run(f"q{count}")
    for number in range(count):
        person(run, str(number), f"Jana {number}", f"Pocet{count}@Example.org")
    with CaptureQueriesContext(connection) as queries:
        found = retention.search_email(f" pocet{count}@EXAMPLE.org ")
    assert len(found) == count
    return queries.captured_queries


def test_an_email_search_runs_the_same_number_of_queries_for_any_number_of_people():
    """AC-146: the work is in the index, not in a loop over every participant."""
    few, many = search_queries(3), search_queries(30)
    assert len(few) == len(many)
    for query in (*few, *many):  # the database narrows it down, Python does not
        where = query["sql"].partition(" WHERE ")[2]
        assert '"email_key"' in where


def test_the_longest_address_whose_key_grows_is_stored_and_found():
    """AC-146: casefold turns one ligature into three letters, and the key must have room."""
    run = a_run()
    address = "\ufb03" * 254
    who = person(run, "1", "Jana", address)

    key = participants.email_key_of(address)
    assert key is not None and len(key) == 762
    assert Participant._meta.get_field("email_key").max_length >= len(key)
    assert [row.participant_id for row in retention.search_email(address)] == ids(who)
    assert Participant.objects.get(pk=who.pk).email_key == key


def test_a_row_without_a_key_is_not_found():
    """AC-146: the migration fills the key of old rows, so a row left without one is invisible."""
    run = a_run()
    who = person(run, "1", "Jana", ADDRESS)
    Participant.objects.filter(pk=who.pk).update(email_key=None)

    assert retention.search_email(ADDRESS) == []


def test_a_name_search_compares_the_name_key():
    """AC-116: a nickname can belong to different people, so every run's holder is listed."""
    first, second = a_run("a"), a_run("b")
    one = person(first, "1", "Jana Nová")
    two = person(second, "2", "JANA   nová")
    person(first, "3", "Jana")

    found = retention.search_name("  jana  NOVÁ ")

    assert {row.participant_id for row in found} == set(ids(one, two))


@pytest.mark.parametrize("typed", ["", "   "])
def test_an_empty_search_finds_nobody_though_people_have_no_name_or_address(typed):
    """AC-116: an empty name key belongs to everybody who gave no name, which means nobody."""
    run = a_run()
    person(run, "1")
    person(run, "2", "", "")

    assert retention.search_email(typed) == []
    assert retention.search_name(typed) == []


def test_erasing_removes_only_the_chosen_people_and_leaves_the_open_run_alone(media_path):
    """AC-116: attempts, answers, photos, entitlements go; others, pseudonyms and the run stay."""
    run = a_run()
    chosen = person(run, "1", "Jana", ADDRESS)
    other = person(run, "2", "Jana", "other@example.org")
    gone_photo, kept_photo = photo(media_path), photo(media_path)
    attempt_of(run, chosen, assets=[gone_photo])
    attempt_of(run, chosen, status=Attempt.Status.IN_PROGRESS)
    kept_attempt = attempt_of(run, other, assets=[kept_photo])
    entry = entitlement_and_draw_entry(run, chosen)

    retention.erase(ids(chosen), admin_id=ADMIN_ID)

    assert list(Participant.objects.filter(run=run)) == [other]
    assert list(Attempt.objects.filter(run=run)) == [kept_attempt]
    assert AttemptAnswer.objects.filter(attempt__run=run).count() == 1
    assert not RewardEntitlement.objects.filter(run=run).exists()
    assert list(MediaAsset.objects.values_list("pk", flat=True).order_by("pk")) == [
        MediaAsset.objects.get(pk=kept_photo).pk
    ]
    assert [p.name for p in media_path.glob("*.webp")] == [f"{kept_photo}.webp"]
    entry.refresh_from_db()
    assert entry.participant_id is None
    assert entry.pseudonym == "pseudo"
    run.refresh_from_db()
    assert run.status == QuizRun.Status.OPEN
    assert run.data_deleted_at is None
    assert run.retention_summary_json in (None, {})


def test_erasing_works_on_a_test_run(media_path):
    """AC-116: a test run counts in an erasure like any other."""
    run = a_test_run()
    chosen = person(run, "1", "Jana", ADDRESS)
    attempt_of(run, chosen, assets=[photo(media_path)])

    retention.erase(ids(chosen), admin_id=ADMIN_ID, email=TYPED)

    assert not Participant.objects.filter(pk=chosen.pk).exists()
    assert len(records(run)) == 1


def test_a_link_from_an_attempt_that_stays_does_not_stop_the_erasure():
    """AC-116: `replaced_by` protects its target, whoever the attempt pointing at it belongs to."""
    run = a_run()
    chosen, other = person(run, "1", "Jana"), person(run, "2", "Eva")
    target = attempt_of(run, chosen)
    staying = attempt_of(run, other, status=Attempt.Status.SWITCHED)
    Attempt.objects.filter(pk=staying.pk).update(replaced_by=target)

    retention.erase(ids(chosen), admin_id=ADMIN_ID)

    staying.refresh_from_db()
    assert staying.replaced_by_id is None
    assert not Attempt.objects.filter(pk=target.pk).exists()


def test_a_chain_of_the_persons_own_attempts_is_erased():
    """AC-116: a replaced attempt and the one that replaced it go together."""
    run = a_run()
    chosen = person(run, "1", "Jana")
    old = attempt_of(run, chosen, status=Attempt.Status.SWITCHED)
    new = attempt_of(run, chosen)
    Attempt.objects.filter(pk=old.pk).update(replaced_by=new)

    retention.erase(ids(chosen), admin_id=ADMIN_ID)

    assert not Attempt.objects.filter(run=run).exists()


def test_attempts_beyond_one_batch_are_all_erased(monkeypatch):
    """AC-116: an erasure is one transaction per run; the batch size only sets its step."""
    monkeypatch.setattr(retention, "BATCH", 1)
    run = a_run()
    chosen = person(run, "1", "Jana")
    for _ in range(3):
        attempt_of(run, chosen)

    retention.erase(ids(chosen), admin_id=ADMIN_ID)

    assert not Attempt.objects.filter(run=run).exists()
    assert records(run)[0].counts_json["attempts"] == 3


def test_an_export_naming_the_run_goes(media_path):
    """AC-116: a file with the person's row must not outlive the erasure."""
    run = a_run()
    chosen = person(run, "1", "Jana", ADDRESS)
    job, directory = done_export(media_path, run)

    retention.erase(ids(chosen), admin_id=ADMIN_ID)

    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert not directory.exists()


def test_an_export_that_cannot_be_removed_leaves_the_erasure_to_be_repeated(
    media_path, monkeypatch
):
    """AC-116: nothing is deleted or recorded, so the retry finds the person and counts in full."""
    run = a_run()
    chosen = person(run, "1", "Jana", ADDRESS)
    attempt_of(run, chosen, assets=[photo(media_path)])
    exporter = registry.get("results_exporter", "csv")
    real = type(exporter).delete_for_runs
    failing = {"left": 1}

    def fails_once(self, quiz_id, run_ids):
        if failing["left"]:
            failing["left"] -= 1
            raise OSError("disk")
        real(self, quiz_id, run_ids)

    monkeypatch.setattr(type(exporter), "delete_for_runs", fails_once)

    with pytest.raises(OSError):
        retention.erase(ids(chosen), admin_id=ADMIN_ID, email=TYPED)

    assert [row.participant_id for row in retention.search_email(TYPED)] == ids(chosen)
    assert Attempt.objects.filter(participant=chosen).exists()
    assert MediaAsset.objects.exists()
    assert records(run) == NO_RECORD_YET

    retention.erase(ids(chosen), admin_id=ADMIN_ID, email=TYPED)

    assert retention.search_email(TYPED) == []
    assert records(run)[0].counts_json["attempts"] == 1
    assert records(run)[0].counts_json["photos"] == 1


def test_a_photo_that_cannot_be_removed_does_not_undo_the_erasure(media_path, monkeypatch, caplog):
    """AC-116: the sweep finds the file later, and the log has the exception type only."""
    run = a_run()
    chosen = person(run, "1", "Jana", ADDRESS)
    attempt_of(run, chosen, assets=[photo(media_path)])
    storage = registry.get("media_storage", "local")

    def fails(self, asset_id):
        raise OSError(ADDRESS)

    monkeypatch.setattr(type(storage), "delete_image", fails)

    with caplog.at_level(logging.ERROR):
        retention.erase(ids(chosen), admin_id=ADMIN_ID, email=TYPED)

    assert not Participant.objects.filter(pk=chosen.pk).exists()
    assert "OSError" in caplog.text
    assert ADDRESS not in caplog.text
    assert len(records(run)) == 1


def test_a_board_cache_that_cannot_be_cleared_does_not_skip_the_files(
    media_path, monkeypatch, caplog
):
    """AC-146: the erasure stands, so the photos and the late exports still go; type only logged."""
    run = a_run()
    chosen = person(run, "1", "Jana", ADDRESS)
    attempt_of(run, chosen, assets=[photo(media_path)])
    late = []

    def broken(run_id):
        raise ConnectionError(ADDRESS)

    monkeypatch.setattr(results, "clear_board_cache", broken)
    monkeypatch.setattr(retention, "_delete_late_exports", lambda found: late.append(found.pk))

    with caplog.at_level(logging.ERROR):
        retention.erase(ids(chosen), admin_id=ADMIN_ID, email=TYPED)

    assert not Participant.objects.filter(pk=chosen.pk).exists()
    assert not MediaAsset.objects.exists()
    assert late == [run.pk]
    assert "ConnectionError" in caplog.text and ADDRESS not in caplog.text
    assert len(records(run)) == 1


def test_ids_nobody_has_change_nothing():
    """AC-116: repeating an erasure that already happened is harmless and adds no record."""
    run = a_run()
    chosen = person(run, "1", "Jana", ADDRESS)
    retention.erase(ids(chosen), admin_id=ADMIN_ID, email=TYPED)
    before = RetentionJob.objects.count()

    retention.erase(ids(chosen), admin_id=ADMIN_ID, email=TYPED)
    retention.erase([], admin_id=ADMIN_ID)

    assert RetentionJob.objects.count() == before


def test_a_person_erased_by_someone_else_meanwhile_gets_no_second_record(monkeypatch):
    """AC-117: a double submission must not add a record saying that nothing was deleted."""
    run = a_run()
    chosen = person(run, "1", "Jana", ADDRESS)
    real = retention._delete_exports

    def other_request_finishes_first(found):
        real(found)
        Participant.objects.filter(pk=chosen.pk).delete()

    monkeypatch.setattr(retention, "_delete_exports", other_request_finishes_first)

    retention.erase(ids(chosen), admin_id=ADMIN_ID, email=TYPED)

    assert records(run) == NO_RECORD_YET
    assert not AuditEvent.objects.filter(action="run.participants_erased").exists()


def test_each_affected_run_gets_its_own_record_with_its_own_counts(media_path):
    """AC-117: who, which run and how many of each kind, one row per run."""
    first, second, untouched = a_run("a"), a_run("b"), a_run("c")
    one, two = person(first, "1", "Jana", ADDRESS), person(second, "2", "Jana", ADDRESS)
    attempt_of(first, one, assets=[photo(media_path), photo(media_path)])
    attempt_of(first, one)
    entitlement_and_draw_entry(first, one)
    attempt_of(second, two)
    person(untouched, "3", "Eva")

    retention.erase(ids(one, two), admin_id=ADMIN_ID, email=TYPED)

    [row] = records(first)
    assert row.trigger == "erasure"
    assert row.admin_id == ADMIN_ID
    assert row.counts_json == {
        "attempts": 2,
        "answers": 2,
        "participants": 1,
        "entitlements": 1,
        "hidden_values": 0,
        "photos": 2,
    }
    assert records(second)[0].counts_json["attempts"] == 1
    assert records(untouched) == NO_RECORD_YET


def test_an_erased_address_is_confirmed_by_typing_it_again_and_is_stored_nowhere():
    """AC-117: the fingerprint answers the question, and no column holds the address."""
    run = a_run()
    chosen = person(run, "1", "Jana", ADDRESS)
    attempt_of(run, chosen)

    retention.erase(ids(chosen), admin_id=ADMIN_ID, email=ADDRESS)

    [found] = retention.erased_records(TYPED)
    assert found.run_id == str(run.pk)
    assert found.trigger == "erasure"
    assert found.admin_id == ADMIN_ID
    assert found.has_fingerprint is True
    assert retention.erased_records("nekdo.jiny@example.org") == []

    trail = [*RetentionJob.objects.values(), *AuditEvent.objects.values()]
    written = str(trail).casefold()
    assert ADDRESS.casefold() not in written
    assert "jana" not in written
    event = AuditEvent.objects.get(action="run.participants_erased", entity_id=str(run.pk))
    assert event.actor_type == "admin"
    assert event.actor_id == ADMIN_ID
    assert list(event.details_json) == ["counts"]
    assert set(event.details_json["counts"]) == {
        "attempts",
        "answers",
        "participants",
        "entitlements",
        "hidden_values",
        "photos",
    }


def test_the_fingerprint_is_a_keyed_hash_of_the_normalised_address():
    """AC-117: its own purpose label, and the same value whatever the address's case or spaces."""
    expected = salted_hmac(
        "kvz-erasure", ADDRESS.strip().casefold(), algorithm="sha256"
    ).hexdigest()

    assert retention.fingerprint(ADDRESS) == expected
    assert retention.fingerprint(TYPED) == expected


def test_an_erasure_by_name_stores_no_fingerprint():
    """AC-117: a nickname search leaves counts only."""
    run = a_run()
    chosen = person(run, "1", "Jana")

    retention.erase(ids(chosen), admin_id=ADMIN_ID)

    [row] = records(run)
    assert row.fingerprint is None
    assert retention.erased_records("") == []


def test_a_board_read_after_an_erasure_no_longer_shows_the_person():
    """AC-146: a nickname erased must not stay on the board for the seconds it is cached."""
    run = authoring.open_run(
        published_quiz("tabule", questions=2),
        admin_id=ADMIN_ID,
        data={"profile": "answers"},
        results={"scoreboard_visibility": "live"},
    )
    chosen = person(run, "1", "Jana", ADDRESS)
    other = person(run, "2", "Eva")
    attempt_of(run, chosen)
    attempt_of(run, other)
    cache.clear()

    def names():
        board = results.board(run, audience="public", locale="cs")
        return sorted(row.label for row in board.tables[0].rows)

    assert names() == ["Eva", "Jana"]  # now cached

    retention.erase(ids(chosen), admin_id=ADMIN_ID, email=ADDRESS)

    assert names() == ["Eva"]


def test_clearing_the_board_cache_covers_every_language_of_the_run():
    """AC-146: the key is built per language, so every one of them goes."""
    run = a_run()
    run.refresh_from_db()
    locales = set(run.quiz.supported_locales) | set(
        run.current_revision.snapshot_json.get("locales", [])
    )
    assert locales
    for locale in locales:
        cache.set(f"kvz-board:{run.pk}:{locale}", "x", 60)
    cache.set("kvz-board:other:cs", "y", 60)

    results.clear_board_cache(run.pk)

    assert all(cache.get(f"kvz-board:{run.pk}:{locale}") is None for locale in locales)
    assert cache.get("kvz-board:other:cs") == "y"


def test_an_erasure_during_a_stopped_purge_takes_its_rows_off_the_summary_counts(
    media_path, monkeypatch
):
    """AC-111: the purge counted every row when it began, so the erasure subtracts its own."""
    run = a_run()
    jana, eva = person(run, "a", "Jana"), person(run, "b", "Eva")
    attempt_of(run, jana, assets=[photo(media_path)])
    attempt_of(run, eva, assets=[None])
    entitlement_and_draw_entry(run, jana)

    def refuse(_run):
        raise OSError("disk")

    with monkeypatch.context() as patch:
        patch.setattr(retention, "_delete_exports", refuse)
        with pytest.raises(OSError):
            retention.purge_run(run, trigger=retention.MANUAL, admin_id=ADMIN_ID)
    started = dict(QuizRun.objects.get(pk=run.pk).retention_summary_json["counts"])
    assert started["participants"] == 2

    retention.erase([str(jana.pk)], admin_id=ADMIN_ID)
    assert retention.purge_run(run, trigger=retention.AUTOMATIC, admin_id=None) is True

    erasure = RetentionJob.objects.get(run_id=str(run.pk), trigger=retention.ERASURE)
    purge = RetentionJob.objects.get(run_id=str(run.pk), trigger=retention.MANUAL)
    for key in ("attempts", "answers", "participants", "entitlements", "photos"):
        assert erasure.counts_json[key] + purge.counts_json[key] == started[key], key
    assert erasure.counts_json["participants"] == 1
    assert purge.counts_json["participants"] == 1
    assert purge.counts_json["hidden_values"] == started["hidden_values"]


def test_an_erasure_in_a_run_with_no_purge_started_leaves_no_summary(media_path):
    run = a_run()
    jana = person(run, "a", "Jana")
    attempt_of(run, jana, assets=[])

    retention.erase([str(jana.pk)], admin_id=ADMIN_ID)

    assert QuizRun.objects.get(pk=run.pk).retention_summary_json == {}


def test_a_summary_that_counts_less_than_the_erasure_is_clamped_and_logged(caplog):
    """AC-111: a negative count would mean an inconsistency, so it is logged (counts only)."""
    run = a_run()
    jana = person(run, "a", "Jana", email=ADDRESS)
    attempt_of(run, jana, assets=[])
    summary = {"counts": {"attempts": 0, "answers": 0, "participants": 0}, "trigger": "manual"}
    QuizRun.objects.filter(pk=run.pk).update(retention_summary_json=summary)

    with caplog.at_level(logging.ERROR, logger="app.domain.retention"):
        retention.erase([str(jana.pk)], admin_id=ADMIN_ID)

    counts = QuizRun.objects.get(pk=run.pk).retention_summary_json["counts"]
    assert counts["participants"] == counts["attempts"] == 0
    assert "summary counts" in caplog.text
    assert str(run.pk) in caplog.text
    assert ADDRESS not in caplog.text

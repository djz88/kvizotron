from decimal import Decimal

import pytest

from app.contracts import EXTERNAL_IMAGE_MODE
from app.domain import (
    authoring,
    bank_folders,
    banks,
    quiz_state,
    revision_diff,
    selection,
    settings,
)
from app.domain.models import BankQuestion
from tests.domain.helpers import (
    ADMIN_ID,
    add_bank_question,
    add_question,
    add_row,
    bank_with,
    definition,
    make_bank,
    make_quiz,
)

pytestmark = pytest.mark.django_db


def row_of(bank, tag="", points=1, count=1):
    return {"bank_id": str(bank.id), "tag": tag, "points": points, "count": count}


def problems(quiz):
    return [(problem.code, problem.detail) for problem in authoring.validate_for_publication(quiz)]


def published_pool(quiz):
    return authoring.latest_published(quiz).snapshot_json["draws"][0]["pool"]


def test_missing_language_is_left_out_of_the_pool():
    bank = bank_with(2, locales=("cs", "uk"))
    only_cs = add_bank_question(bank, ("cs",))
    pool = banks.pool(row_of(bank), ["cs", "uk"])
    assert len(pool) == 2
    assert only_cs not in {question["id"] for question in pool}


def test_usable_count_shows_usable_of_all_matching_the_tag():
    bank = bank_with(17, locales=("cs", "uk"), tags=("a",))
    for _ in range(3):
        add_bank_question(bank, ("cs",), tags=("a",))
    add_bank_question(bank, ("cs", "uk"), tags=("b",))
    assert banks.usable_count(row_of(bank, tag="a"), ["cs", "uk"]) == (17, 20)


def test_publication_copies_the_pool_with_row_points():
    bank = bank_with(3)
    quiz = make_quiz()
    add_row(quiz, bank, count=2, points=5)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    pool = published_pool(quiz)
    assert len(pool) == 3
    assert {question["settings"]["points"] for question in pool} == {5}
    assert all("scoring_version" in question for question in pool)


def test_max_score_is_own_plus_count_times_points():
    bank = bank_with(3)
    quiz = make_quiz()
    add_question(quiz)
    add_row(quiz, bank, count=2, points=5)
    assert authoring.publish(quiz, admin_id=ADMIN_ID).max_score == Decimal(11)


def test_plugins_of_pool_questions_are_recorded():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    revision = authoring.publish(quiz, admin_id=ADMIN_ID)
    assert "choice" in revision.plugins_json["question_types"]


def test_blocked_only_when_rows_cannot_be_filled():
    bank = bank_with(2)
    quiz = make_quiz()
    add_row(quiz, bank, count=3)
    assert [code for code, _ in problems(quiz)] == ["draw_not_enough"]
    assert bank.name in problems(quiz)[0][1]


def test_overlapping_rows_are_checked_together():
    bank = bank_with(3)
    quiz = make_quiz()
    add_row(quiz, bank, count=2)
    add_row(quiz, bank, count=2)
    assert [code for code, _ in problems(quiz)] == ["draw_not_enough"]
    add_bank_question(bank)
    assert problems(quiz) == []


def test_greedy_would_fail_but_assign_succeeds():
    rows = [
        {"id": "wide", "count": 1, "pool": [{"id": "1"}, {"id": "2"}]},
        {"id": "narrow", "count": 1, "pool": [{"id": "1"}]},
    ]
    for _ in range(20):
        assert selection.assign(rows) == {"wide": ["2"], "narrow": ["1"]}


def test_assign_reports_the_impossible():
    rows = [
        {"id": "a", "count": 1, "pool": [{"id": "1"}]},
        {"id": "b", "count": 1, "pool": [{"id": "1"}]},
    ]
    assert selection.assign(rows) is None


def test_quiz_with_only_draw_rows_publishes():
    quiz = make_quiz()
    add_row(quiz, bank_with(2))
    assert problems(quiz) == []
    assert authoring.publish(quiz, admin_id=ADMIN_ID).max_score == 1


def test_quiz_with_nothing_still_has_no_questions():
    assert [code for code, _ in problems(make_quiz())] == ["no_questions"]


def test_language_added_after_publication_recounts_and_blocks():
    bank = bank_with(2)
    quiz = make_quiz()
    add_row(quiz, bank, count=2)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    quiz.supported_locales = ["cs", "uk"]
    quiz.title = {"cs": "T", "uk": "T"}
    quiz.description = {"cs": "P", "uk": "P"}
    quiz.save()
    assert banks.usable_count(authoring.editable_draws(quiz)[0], quiz.supported_locales) == (0, 2)
    assert authoring.banks_changed(quiz)
    assert "draw_not_enough" in [code for code, _ in problems(quiz)]


def test_bank_edit_leaves_revision_unchanged():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    revision = authoring.publish(quiz, admin_id=ADMIN_ID)
    before = revision.snapshot_json
    add_bank_question(bank, prompt="Nová")
    revision.refresh_from_db()
    assert revision.snapshot_json == before


def test_no_change_means_no_unpublished_changes():
    bank = bank_with(2)
    quiz = make_quiz()
    add_row(quiz, bank)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    assert not authoring.banks_changed(quiz)
    assert not quiz_state.of(quiz).has_changes


def test_bank_edit_shows_unpublished_changes():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    add_bank_question(bank, prompt="Nová")
    state = quiz_state.of(quiz)
    assert state.has_changes
    assert state.needs_publication_page


def test_new_question_with_another_tag_changes_nothing():
    bank = bank_with(1, tags=("a",))
    quiz = make_quiz()
    add_row(quiz, bank, tag="a")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    add_bank_question(bank, tags=("b",))
    assert not authoring.banks_changed(quiz)


def test_bank_change_can_be_published_without_a_draft():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    first = authoring.publish(quiz, admin_id=ADMIN_ID)
    add_bank_question(bank, prompt="Nová")
    assert not authoring.has_draft(quiz)
    second = authoring.publish(quiz, admin_id=ADMIN_ID)
    assert second.revision_no == first.revision_no + 1
    assert len(second.snapshot_json["draws"][0]["pool"]) == 2
    assert not authoring.has_changes(quiz)


def test_nothing_to_publish_without_a_change_still_refused():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    with pytest.raises(authoring.PublicationError):
        authoring.publish(quiz, admin_id=ADMIN_ID)


def test_nothing_to_discard_when_only_a_bank_changed():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    add_bank_question(bank, prompt="Nová")
    assert quiz_state.of(quiz).has_changes
    assert quiz_state.SecondaryAction.DISCARD not in quiz_state.of(quiz).secondary


def compare(quiz):
    return revision_diff.compare(
        authoring.latest_published(quiz).snapshot_json,
        authoring.future_snapshot(quiz),
        ["cs"],
    )


def test_change_overview_lists_added_changed_removed_bank_questions():
    bank = bank_with(2)
    quiz = make_quiz()
    add_row(quiz, bank, count=1)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    first, second = BankQuestion.objects.order_by("id")
    add_bank_question(bank, prompt="Přidaná")
    banks.delete_question(bank, first.pk, admin_id=ADMIN_ID)
    banks.save_question(
        bank,
        str(second.pk),
        "choice",
        definition(("cs",), prompt="Změněná"),
        locales=("cs",),
        tags=(),
    )
    diff = compare(quiz)
    assert not diff.is_empty
    assert [change.label for change in diff.bank_added][0].startswith("Přidaná")
    assert [change.label for change in diff.bank_removed][0].startswith("Banka")
    assert [change.label for change in diff.bank_changed][0].startswith("Změněná")


def test_change_overview_lists_a_changed_row():
    bank = bank_with(3)
    quiz = make_quiz()
    row = add_row(quiz, bank, count=1)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    authoring.save_draw(quiz, row, bank_id=str(bank.id), tag="", count=2, points=1, position=0)
    assert compare(quiz).draws


def test_returning_to_an_old_revision_keeps_rows_and_rereads_the_bank():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    old = authoring.publish(quiz, admin_id=ADMIN_ID)
    add_bank_question(bank, prompt="Nová")
    authoring.use_as_draft(quiz, old, admin_id=ADMIN_ID)
    assert "pool" not in authoring.editable_draws(quiz)[0]
    assert len(authoring.publish(quiz, admin_id=ADMIN_ID).snapshot_json["draws"][0]["pool"]) == 2


def test_returning_with_a_deleted_bank_blocks_publication():
    bank = bank_with(1)
    quiz = make_quiz()
    add_question(quiz)
    row = add_row(quiz, bank)
    old = authoring.publish(quiz, admin_id=ADMIN_ID)
    authoring.delete_draw(quiz, row)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    banks.delete(bank, admin_id=ADMIN_ID)
    authoring.use_as_draft(quiz, old, admin_id=ADMIN_ID)
    assert [code for code, _ in problems(quiz)] == ["draw_bank_missing"]
    authoring.delete_draw(quiz, row)
    assert problems(quiz) == []


def test_duplicate_copies_rows():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    copy = authoring.duplicate_quiz(quiz, "kopie", admin_id=ADMIN_ID)
    assert authoring.editable_draws(copy)[0]["bank_id"] == str(bank.id)


def test_stale_publication_refused_after_a_bank_edit():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    seen = authoring.snapshot_hash(quiz)
    add_bank_question(bank, prompt="Nová")
    with pytest.raises(authoring.StalePublication):
        authoring.publish(quiz, admin_id=ADMIN_ID, expected_hash=seen)


def test_draft_keeps_rows_without_pools():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    add_question(quiz)
    assert "pool" not in authoring.editable_draws(quiz)[0]


def test_old_revision_without_rows_reads_as_none():
    quiz = make_quiz()
    add_question(quiz)
    revision = authoring.publish(quiz, admin_id=ADMIN_ID)
    snapshot = dict(revision.snapshot_json)
    snapshot.pop("draws", None)
    type(revision).objects.filter(pk=revision.pk).update(snapshot_json=snapshot)
    assert authoring.editable_draws(quiz) == []
    assert not authoring.banks_changed(quiz)
    assert selection.count(snapshot) == 1


def test_pool_question_of_a_missing_type_is_not_usable():
    bank = bank_with(1)
    question = BankQuestion.objects.get()
    question.question_json["type"] = "gone.type"
    question.save()
    assert banks.usable_count(row_of(bank), ["cs"]) == (0, 1)


def test_deleting_an_own_question_keeps_the_row_in_place():
    bank = bank_with(1)
    quiz = make_quiz()
    first = add_question(quiz)
    add_question(quiz)
    add_row(quiz, bank, position=1)
    authoring.delete_question(quiz, first)
    assert authoring.editable_draws(quiz)[0]["position"] == 0


def test_bank_change_during_an_open_run_asks_for_publication():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    add_bank_question(bank, prompt="Nová")
    state = quiz_state.of(quiz)
    assert state.main == quiz_state.MainAction.PUBLISH_CHANGES
    revision = authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)
    run.refresh_from_db()
    assert run.current_revision == revision
    assert quiz_state.of(quiz).main == quiz_state.MainAction.END_RUN


def _bank_with_no_copy(**setting_values):
    bank = make_bank()
    alt = {"cs": "P", "en": "P", "uk": "P"}
    image = {"asset": None, "source": "https://a.example/1.png", "alt": alt}
    config = definition(("cs", "en", "uk")) | {"image": image}
    banks.save_question(
        bank,
        None,
        "choice",
        config,
        locales=("cs", "en", "uk"),
        tags=(),
        setting_values=setting_values or None,
    )
    return bank


def test_a_draw_pool_is_checked_against_this_quiz():
    quiz = make_quiz()
    bank = _bank_with_no_copy()
    authoring.save_draw(quiz, None, bank_id=str(bank.id), tag="", count=1, points=1, position=0)
    assert problems(quiz) == [("draw_image_no_copy", bank.name)]
    settings.set_override(EXTERNAL_IMAGE_MODE, quiz, "external", admin_id=ADMIN_ID)
    assert problems(quiz) == []


def test_a_bank_question_set_to_external_stays_allowed():
    quiz = make_quiz()
    bank = _bank_with_no_copy(**{EXTERNAL_IMAGE_MODE: "external"})
    authoring.save_draw(quiz, None, bank_id=str(bank.id), tag="", count=1, points=1, position=0)
    assert problems(quiz) == []


def folder_bank():
    """EU(1 own) -> trade(2), geo(1); one question with the tag `old`; one unfiled."""
    bank = make_bank()
    eu = bank_folders.create(bank, None, "EU", admin_id=ADMIN_ID)
    trade = bank_folders.create(bank, eu, "trade", admin_id=ADMIN_ID)
    geo = bank_folders.create(bank, eu, "geo", admin_id=ADMIN_ID)
    placed = {}
    for name, folder, tags in (
        ("eu", eu, ()),
        ("trade1", trade, ("old",)),
        ("trade2", trade, ()),
        ("geo1", geo, ()),
        ("loose", None, ()),
    ):
        placed[name] = add_bank_question(bank, prompt=name, tags=tags, folder=folder)
    return bank, {"eu": eu, "trade": trade, "geo": geo}, placed


def pool_ids(row, locales=("cs",)):
    return {question["id"] for question in banks.pool(row, locales)}


def test_pool_of_a_folder_includes_subfolders():
    """AC-154: a draw row by folder draws from the folder and everything below it."""
    bank, folders, placed = folder_bank()
    base = {"bank_id": str(bank.id), "tag": "", "points": 1, "count": 1}
    assert pool_ids(base | {"folder_id": str(folders["eu"].pk)}) == {
        placed[name] for name in ("eu", "trade1", "trade2", "geo1")
    }
    assert pool_ids(base | {"folder_id": str(folders["trade"].pk)}) == {
        placed["trade1"],
        placed["trade2"],
    }
    assert banks.usable_count(base | {"folder_id": str(folders["trade"].pk)}, ["cs"]) == (2, 2)


def test_folder_and_tag_must_both_match():
    bank, folders, placed = folder_bank()
    row = {"bank_id": str(bank.id), "points": 1, "count": 1}
    row |= {"folder_id": str(folders["eu"].pk), "tag": "OLD"}
    assert pool_ids(row) == {placed["trade1"]}
    assert pool_ids(row | {"folder_id": str(folders["geo"].pk)}) == set()


def test_a_row_with_no_folder_draws_the_whole_bank_unfiled_included():
    bank, _folders, placed = folder_bank()
    base = {"bank_id": str(bank.id), "tag": "", "points": 1, "count": 1}
    assert pool_ids(base) == set(placed.values())
    assert pool_ids(base | {"folder_id": ""}) == set(placed.values())


def test_a_folder_of_another_bank_is_refused_in_a_row():

    bank = make_bank("A")
    foreign = bank_folders.create(make_bank("B"), None, "x", admin_id=ADMIN_ID)
    with pytest.raises(bank_folders.WrongBank):
        add_row(make_quiz(), bank, folder_id=str(foreign.pk))


def test_a_row_keeps_the_folder_path_and_label():
    bank, folders, _placed = folder_bank()
    quiz = make_quiz()
    add_row(quiz, bank, tag="old", folder_id=str(folders["trade"].pk))
    row = authoring.editable_draws(quiz)[0]
    assert (row["folder_id"], row["folder_path"]) == (str(folders["trade"].pk), "EU/trade")
    assert authoring._row_label(row) == f"{bank.name} (EU/trade · old)"


def test_published_revision_does_not_change_when_a_folder_is_renamed_or_moved():
    """AC-32: a bank edit leaves the published revision as it is."""
    bank, folders, placed = folder_bank()
    quiz = make_quiz()
    add_row(quiz, bank, folder_id=str(folders["eu"].pk))
    revision = authoring.publish(quiz, admin_id=ADMIN_ID)
    before = revision.snapshot_json
    bank_folders.rename(folders["trade"], "commerce", admin_id=ADMIN_ID)
    bank_folders.move(folders["geo"], None, admin_id=ADMIN_ID)
    assert authoring.latest_published(quiz).snapshot_json == before
    assert authoring.banks_changed(quiz) is True  # geo1 left the folder: the bank pool changed
    bank_folders.move(folders["geo"], folders["eu"], admin_id=ADMIN_ID)
    assert authoring.banks_changed(quiz) is False
    bank_folders.move_questions(bank, [placed["trade1"]], None, admin_id=ADMIN_ID)
    assert authoring.latest_published(quiz).snapshot_json == before
    assert authoring.banks_changed(quiz) is True


def test_revision_overview_shows_a_changed_folder():
    bank, folders, _placed = folder_bank()
    quiz = make_quiz()
    row = add_row(quiz, bank, folder_id=str(folders["eu"].pk))
    authoring.publish(quiz, admin_id=ADMIN_ID)
    authoring.save_draw(
        quiz,
        row,
        bank_id=str(bank.id),
        tag="",
        folder_id=str(folders["trade"].pk),
        count=1,
        points=1,
        position=0,
    )
    (change,) = compare(quiz).draws
    assert "EU" in change.before and "EU/trade" in change.after


def test_save_draw_stores_and_refuses_a_difficulty():
    bank = make_bank()
    quiz = make_quiz()
    add_row(quiz, bank, difficulty="hard")
    add_row(quiz, bank)
    assert [row["difficulty"] for row in authoring.editable_draws(quiz)] == ["hard", ""]
    with pytest.raises(ValueError):
        add_row(quiz, bank, difficulty="impossible")


def test_the_label_and_the_change_overview_show_a_level_only_when_set():
    bank = bank_with(1)
    quiz = make_quiz()
    add_row(quiz, bank, tag="EU", difficulty="easy")
    assert authoring._row_label(authoring.editable_draws(quiz)[0]) == (
        f"{bank.name} (EU · {banks.level_label('easy')})"
    )
    plain = make_quiz("jiny")
    add_row(plain, bank, tag="EU")
    assert authoring._row_label(authoring.editable_draws(plain)[0]) == f"{bank.name} (EU)"
    assert revision_diff._draw_text(authoring.editable_draws(quiz)[0]).endswith(
        banks.level_label("easy")
    )
    assert banks.level_label("easy") not in revision_diff._draw_text(
        authoring.editable_draws(plain)[0]
    )


def test_a_row_without_the_key_and_one_saved_with_an_empty_difficulty_are_no_change():
    bank = bank_with(1)
    quiz = make_quiz()
    row = add_row(quiz, bank)
    stored = authoring.get_draft(quiz)
    del stored.snapshot_json["draws"][0]["difficulty"]
    stored.save()
    authoring.publish(quiz, admin_id=ADMIN_ID)
    authoring.save_draw(
        quiz,
        row,
        bank_id=str(bank.id),
        tag="",
        count=1,
        points=1,
        position=authoring.editable_draws(quiz)[0]["position"],
    )
    assert compare(quiz).draws == []

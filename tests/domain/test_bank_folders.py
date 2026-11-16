"""Folders in a question bank (AC-153)."""

from uuid import UUID

import pytest

from app.domain import bank_folders, banks
from app.domain.models import BankFolder, BankQuestion
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, add_bank_question, add_row, make_bank, make_quiz

pytestmark = pytest.mark.django_db


def make(bank, name, parent=None):
    return bank_folders.create(bank, parent, name, admin_id=ADMIN_ID)


def test_create_nested_up_to_four_levels_and_refuse_the_fifth():
    """AC-153: a folder tree is at most four levels deep."""
    bank = make_bank()
    folder = None
    for name in ("a", "b", "c", "d"):
        folder = make(bank, name, folder)
    with pytest.raises(bank_folders.FolderTooDeep):
        make(bank, "e", folder)
    assert BankFolder.objects.filter(bank=bank).count() == 4


@pytest.mark.parametrize("name", ["", "   ", "x" * 81, "a/b"])
def test_invalid_names_are_refused(name):
    with pytest.raises(bank_folders.FolderNameInvalid):
        make(make_bank(), name)


def test_name_is_unique_among_siblings_by_casefold_only():
    bank = make_bank()
    root = make(bank, "Trade")
    with pytest.raises(bank_folders.FolderNameTaken):
        make(bank, "trade")
    other = make(bank, "EU")
    assert make(bank, "Trade", other).parent_id == other.pk
    with pytest.raises(bank_folders.FolderNameTaken):
        bank_folders.rename(other, "TRADE", admin_id=ADMIN_ID)
    assert root.name == "Trade"


def test_move_into_own_descendant_is_refused():
    bank = make_bank()
    top = make(bank, "EU")
    child = make(bank, "trade", top)
    with pytest.raises(bank_folders.FolderCycle):
        bank_folders.move(top, child, admin_id=ADMIN_ID)
    with pytest.raises(bank_folders.FolderCycle):
        bank_folders.move(top, top, admin_id=ADMIN_ID)
    top.refresh_from_db()
    assert top.parent_id is None


def test_move_checks_the_depth_of_the_whole_subtree():
    bank = make_bank()
    deep = make(make_bank(), "x")  # another bank, must not matter
    assert deep.bank_id != bank.id
    a = make(bank, "a")
    b = make(bank, "b", a)
    subtree = make(bank, "s")
    make(bank, "t", make(bank, "u", subtree))  # s -> u -> t, three levels
    with pytest.raises(bank_folders.FolderTooDeep):
        bank_folders.move(subtree, b, admin_id=ADMIN_ID)  # b is level 2, 2 + 3 = 5
    subtree.refresh_from_db()
    assert subtree.parent_id is None
    bank_folders.move(subtree, a, admin_id=ADMIN_ID)  # 1 + 3 = 4
    subtree.refresh_from_db()
    assert subtree.parent_id == a.pk


def test_a_folder_of_another_bank_is_refused():
    one, two = make_bank("A"), make_bank("B")
    foreign = make(two, "x")
    with pytest.raises(bank_folders.WrongBank):
        make(one, "y", foreign)


def test_delete_only_when_empty():
    """AC-153: a folder is deleted only when it holds no question and no subfolder."""
    bank = make_bank()
    folder = make(bank, "EU")
    child = make(bank, "trade", folder)
    with pytest.raises(bank_folders.FolderNotEmpty):
        bank_folders.delete(folder, admin_id=ADMIN_ID)
    question = add_bank_question(bank)
    BankQuestion.objects.filter(pk=question).update(folder=child)
    with pytest.raises(bank_folders.FolderNotEmpty):
        bank_folders.delete(child, admin_id=ADMIN_ID)
    BankQuestion.objects.filter(pk=question).update(folder=None)
    bank_folders.delete(child, admin_id=ADMIN_ID)
    bank_folders.delete(folder, admin_id=ADMIN_ID)
    assert not BankFolder.objects.filter(bank=bank).exists()


def test_path_and_subtree():
    bank = make_bank()
    top = make(bank, "EU")
    child = make(bank, "trade", top)
    grand = make(bank, "tariffs", child)
    assert bank_folders.path_of(grand) == "EU/trade/tariffs"
    assert bank_folders.path_of(None) == ""
    assert bank_folders.subtree_ids(top) == {top.pk, child.pk, grand.pk}
    assert bank_folders.subtree_ids(grand) == {grand.pk}


def test_ensure_path_creates_missing_levels_and_reuses_by_casefold():
    bank = make_bank()
    first = bank_folders.ensure_path(bank, "EU/trade", admin_id=ADMIN_ID)
    again = bank_folders.ensure_path(bank, "eu/Trade", admin_id=ADMIN_ID)
    assert again.pk == first.pk
    assert BankFolder.objects.filter(bank=bank).count() == 2
    assert bank_folders.path_of(first) == "EU/trade"


@pytest.mark.parametrize("path", ["", "EU//x", "/EU", "EU/", "a/b/c/d/e", "x" * 81])
def test_ensure_path_refuses_bad_paths_and_creates_nothing(path):
    bank = make_bank()
    with pytest.raises(bank_folders.FolderError):
        bank_folders.ensure_path(bank, path, admin_id=ADMIN_ID)
    assert not BankFolder.objects.filter(bank=bank).exists()


def test_choices_list_paths_sorted():
    bank = make_bank()
    make(bank, "b")
    make(bank, "a", make(bank, "A"))
    assert [label for _, label in bank_folders.choices(bank)] == ["A", "A/a", "b"]


def test_deleting_a_bank_removes_its_folders():
    bank = make_bank()
    make(bank, "b", make(bank, "a"))
    banks.delete(bank, admin_id=ADMIN_ID)
    assert not BankFolder.objects.exists()


def test_a_bank_in_use_is_still_refused_and_keeps_its_folders():
    bank = make_bank()
    make(bank, "a")
    add_bank_question(bank)
    quiz = make_quiz()
    add_row(quiz, bank)
    with pytest.raises(banks.BankInUse):
        banks.delete(bank, admin_id=ADMIN_ID)
    assert BankFolder.objects.filter(bank=bank).count() == 1


def test_audit_entries_carry_no_personal_data():
    bank = make_bank()
    folder = make(bank, "a")
    bank_folders.rename(folder, "b", admin_id=ADMIN_ID)
    other = make(bank, "c")
    bank_folders.move(folder, other, admin_id=ADMIN_ID)
    bank_folders.delete(folder, admin_id=ADMIN_ID)
    actions = set(
        AuditEvent.objects.filter(action__startswith="bank.folder_").values_list(
            "action", flat=True
        )
    )
    assert actions == {
        "bank.folder_created",
        "bank.folder_renamed",
        "bank.folder_moved",
        "bank.folder_deleted",
    }
    for event in AuditEvent.objects.filter(action__startswith="bank.folder_"):
        assert event.details_json == {}


def paths_of(bank):
    return [path for _id, path in bank_folders.choices(bank)]


def put(question_id, folder):
    BankQuestion.objects.filter(pk=question_id).update(folder=folder)


def test_tree_counts_include_subfolders():
    """AC-153: a folder counts the questions below it and its direct subfolders."""
    bank = make_bank()
    eu = make(bank, "EU")
    trade = make(bank, "trade", eu)
    geo = make(bank, "geo", eu)
    for _ in range(2):
        put(add_bank_question(bank), eu)
    for _ in range(3):
        put(add_bank_question(bank), trade)
    put(add_bank_question(bank), geo)
    (root,) = bank_folders.tree(bank)
    assert (root.folder, root.total, root.subfolders) == (eu, 6, 2)
    assert [(n.folder.name, n.total, n.subfolders) for n in root.children] == [
        ("geo", 1, 0),
        ("trade", 3, 0),
    ]


def test_tree_uses_a_fixed_number_of_queries(django_assert_num_queries):
    bank = make_bank()
    parent = None
    for index in range(4):
        parent = make(bank, f"level{index}", parent)
    for index in range(6):
        put(add_bank_question(bank), make(bank, f"flat{index}"))
    with django_assert_num_queries(2):
        bank_folders.tree(bank)


def test_unfiled_count():
    bank = make_bank()
    add_bank_question(bank)
    put(add_bank_question(bank), make(bank, "a"))
    assert bank_folders.unfiled_count(bank) == 1


def test_search_ignores_case_and_diacritics():
    bank = make_bank()
    found = add_bank_question(bank, prompt="Čeština a Ekonomika")
    add_bank_question(bank, prompt="Jiná")
    assert [row.pk.hex for row in bank_folders.search(bank, "cestina")] == [UUID(found).hex]
    assert len(bank_folders.search(bank, "EKONOMIKA")) == 1


def test_search_does_not_equate_ukrainian_i_and_y():
    bank = make_bank()
    add_bank_question(bank, locales=("cs", "uk"), prompt="Мій")
    assert len(bank_folders.search(bank, "мій")) == 1
    assert bank_folders.search(bank, "миі") == []


def test_search_finds_by_tag_and_folder_path():
    bank = make_bank()
    tagged = add_bank_question(bank, tags=("Středověk",))
    filed = add_bank_question(bank)
    put(filed, make(bank, "Obchod", make(bank, "EU")))
    assert [str(r.pk) for r in bank_folders.search(bank, "stredovek")] == [tagged]
    assert [str(r.pk) for r in bank_folders.search(bank, "eu/obchod")] == [filed]


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_search_returns_nothing(text):
    bank = make_bank()
    add_bank_question(bank)
    assert bank_folders.search(bank, text) == []


def test_move_questions_all_or_nothing():
    """AC-156: a bulk move changes every chosen question, or none."""
    bank, other = make_bank("A"), make_bank("B")
    target = make(bank, "t")
    ids = [add_bank_question(bank) for _ in range(3)]
    foreign = add_bank_question(other)
    assert bank_folders.move_questions(bank, ids[:2], target, admin_id=ADMIN_ID) == 2
    assert BankQuestion.objects.filter(folder=target).count() == 2
    with pytest.raises(bank_folders.WrongBank):
        bank_folders.move_questions(bank, [ids[2], foreign], target, admin_id=ADMIN_ID)
    assert BankQuestion.objects.get(pk=ids[2]).folder_id is None
    with pytest.raises(bank_folders.WrongBank):
        bank_folders.move_questions(bank, [ids[2]], make(other, "x"), admin_id=ADMIN_ID)
    assert bank_folders.move_questions(bank, ids[:2], None, admin_id=ADMIN_ID) == 2
    assert not BankQuestion.objects.filter(folder__isnull=False).exists()
    assert AuditEvent.objects.filter(action="bank.questions_moved").exists()


def test_a_question_can_be_saved_into_a_folder():
    bank = make_bank()
    folder = make(bank, "a")
    question = add_bank_question(bank, folder=folder)
    assert BankQuestion.objects.get(pk=question).folder_id == folder.pk
    with pytest.raises(bank_folders.WrongBank):
        add_bank_question(bank, folder=make(make_bank("B"), "x"))


def eu_bank():
    """EU(1 own question) -> ekonomika(1) -> fondy(1), geopolitika(1)."""
    bank = make_bank("Evropská Unie")
    eu = make(bank, "EU")
    econ = make(bank, "ekonomika", eu)
    funds = make(bank, "fondy", econ)
    geo = make(bank, "geopolitika", eu)
    questions = {}
    for name, folder in (("eu", eu), ("econ", econ), ("funds", funds), ("geo", geo)):
        questions[name] = add_bank_question(bank, prompt=name, tags=("EU",))
        put(questions[name], folder)
    return bank, {"eu": eu, "econ": econ, "funds": funds, "geo": geo}, questions


def test_a_folder_moves_to_another_bank_with_everything_in_it():
    """AC-159: a folder moves to another bank, to its top or under a folder, with its content."""
    bank, folders, questions = eu_bank()
    other = make_bank("XXX")
    bank_folders.transfer(folders["eu"], other, None, admin_id=ADMIN_ID)
    assert paths_of(other) == ["EU", "EU/ekonomika", "EU/ekonomika/fondy", "EU/geopolitika"]
    assert paths_of(bank) == []
    assert BankQuestion.objects.filter(bank=other).count() == 4
    assert BankQuestion.objects.filter(bank=bank).count() == 0
    assert BankQuestion.objects.get(pk=questions["funds"]).tags == ["EU"]
    assert BankFolder.objects.filter(bank=other).count() == 4


def test_a_folder_moves_under_a_folder_of_another_bank():
    bank, folders, _questions = eu_bank()
    other = make_bank("XXX")
    target = make(other, "Evropa")
    bank_folders.transfer(folders["econ"], other, target, admin_id=ADMIN_ID)
    assert paths_of(other) == ["Evropa", "Evropa/ekonomika", "Evropa/ekonomika/fondy"]
    assert paths_of(bank) == ["EU", "EU/geopolitika"]


def test_a_move_to_another_bank_is_all_or_nothing():
    bank, folders, _questions = eu_bank()
    other = make_bank("XXX")
    make(other, "EU")  # the name is taken at the top
    with pytest.raises(bank_folders.FolderNameTaken):
        bank_folders.transfer(folders["eu"], other, None, admin_id=ADMIN_ID)
    deep = None
    for name in ("a", "b", "c"):
        deep = make(other, name, deep)  # three levels: the 3-level subtree of EU cannot go under it
    with pytest.raises(bank_folders.FolderTooDeep):
        bank_folders.transfer(folders["eu"], other, deep, admin_id=ADMIN_ID)
    assert BankFolder.objects.filter(bank=bank).count() == 4
    assert BankQuestion.objects.filter(bank=bank).count() == 4


def test_a_folder_that_a_draw_row_names_does_not_leave_its_bank():
    bank, folders, _questions = eu_bank()
    other = make_bank("XXX")
    quiz = make_quiz(slug="pouziva-slozku")
    add_row(quiz, bank, folder_id=str(folders["funds"].pk))  # names a folder inside the subtree
    with pytest.raises(bank_folders.FolderInUse) as error:
        bank_folders.transfer(folders["eu"], other, None, admin_id=ADMIN_ID)
    assert "pouziva-slozku" in str(error.value)
    with pytest.raises(bank_folders.FolderInUse):
        bank_folders.promote(folders["eu"], admin_id=ADMIN_ID)
    assert BankFolder.objects.filter(bank=bank).count() == 4


def test_a_whole_bank_draw_row_does_not_stop_a_move_and_its_pool_shrinks():
    bank, folders, _questions = eu_bank()
    quiz = make_quiz()
    add_row(quiz, bank)
    row = {"bank_id": str(bank.id), "tag": "", "points": 1, "count": 1}
    assert len(banks.pool(row, ["cs"])) == 4
    bank_folders.transfer(folders["geo"], make_bank("XXX"), None, admin_id=ADMIN_ID)
    assert len(banks.pool(row, ["cs"])) == 3


def test_a_folder_becomes_a_bank_with_its_content_at_the_top():
    """AC-159: a folder becomes a bank of its own; its subfolders are the top of the new bank."""
    bank, folders, questions = eu_bank()
    new = bank_folders.promote(folders["eu"], admin_id=ADMIN_ID)
    assert new.name == "EU" and new.pk != bank.pk
    assert paths_of(new) == ["ekonomika", "ekonomika/fondy", "geopolitika"]
    assert not BankFolder.objects.filter(pk=folders["eu"].pk).exists()
    assert paths_of(bank) == []
    assert BankQuestion.objects.filter(bank=new).count() == 4
    own = BankQuestion.objects.get(pk=questions["eu"])
    assert (own.bank_id, own.folder_id) == (new.pk, None)  # its own question is unfiled there
    assert BankQuestion.objects.get(pk=questions["funds"]).folder_id == folders["funds"].pk


def test_moving_between_banks_and_promoting_are_audited_without_personal_data():
    bank, folders, _questions = eu_bank()
    bank_folders.transfer(folders["geo"], make_bank("XXX"), None, admin_id=ADMIN_ID)
    bank_folders.promote(folders["eu"], admin_id=ADMIN_ID)
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"bank.folder_moved", "bank.folder_promoted", "bank.created"} <= actions
    for event in AuditEvent.objects.filter(
        action__in=["bank.folder_moved", "bank.folder_promoted"]
    ):
        assert event.details_json == {}

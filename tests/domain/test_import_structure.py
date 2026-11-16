"""What the check page of a bank import shows: the folder tree and short draw rows (AC-166)."""

import pytest

from app.contracts import CsvRow, ParsedFile
from app.domain import authoring, bank_folders, banks, import_structure, question_import
from app.domain.import_structure import ShortRow
from app.domain.question_import import Target
from tests.domain.helpers import ADMIN_ID, add_bank_question, add_row, make_bank, make_quiz

pytestmark = pytest.mark.django_db
GOOD = {
    "type": "choice",
    "prompt_cs": "Otázka",
    "prompt_en": "Question",
    "option_1_cs": "A",
    "option_1_en": "A",
    "option_2_cs": "B",
    "option_2_en": "B",
    "correct": "A",
}
ONLY_CS = {"type": "choice", "prompt_cs": "Jen česky", "option_1_cs": "A", "option_2_cs": "B"}


def plan_into(bank, *rows, replace=True):
    columns = list(dict.fromkeys(name for row in rows for name in row))
    parsed = ParsedFile(
        columns,
        [
            CsvRow(number + 2, {column: row.get(column, "") for column in columns})
            for number, row in enumerate(rows)
        ],
        frozenset(),
    )
    return question_import.interpret(parsed, Target("bank", None, bank, replace=replace), {}, None)


def row(folder, **cells):
    return {**GOOD, "folder": folder, **cells}


def folder(bank, path):
    return bank_folders.ensure_path(bank, path, admin_id=ADMIN_ID)


def shape(nodes):
    return [(node.name, node.count, node.exists, shape(node.children)) for node in nodes]


def test_the_tree_marks_existing_and_new_folders_and_counts_below():
    bank = make_bank()
    folder(bank, "Geopolitika")
    plan = plan_into(
        bank, row("geopolitika"), row("ekonomika/fondy"), row("ekonomika"), row(""), replace=False
    )
    structure = import_structure.structure(plan, bank)
    assert shape(structure.folders) == [
        ("ekonomika", 2, False, [("fondy", 1, False, [])]),
        ("geopolitika", 1, True, []),
    ]
    assert structure.without_folder == 1


def test_the_tree_names_bank_folders_the_file_leaves_out():
    bank = make_bank()
    folder(bank, "geopolitika")
    folder(bank, "obchod")
    structure = import_structure.structure(plan_into(bank, row("EU/geopolitika")), bank)
    assert structure.unused == ["geopolitika", "obchod"]
    assert [node.exists for node in structure.folders] == [False]


def test_a_row_on_a_folder_the_file_leaves_empty_is_short():
    """AC-166: the replace check names the draw row that would draw from an empty folder."""
    bank = make_bank()
    obchod = folder(bank, "obchod")
    add_row(make_quiz(slug="evropa"), bank, count=3, folder_id=str(obchod.pk))
    plan = plan_into(bank, row("EU/obchod"))
    assert import_structure.short_rows(plan, bank) == [ShortRow("evropa", "obchod", "", "", 0, 3)]


def test_a_row_that_gets_enough_is_not_listed_and_subfolders_count():
    bank = make_bank()
    ekonomika = folder(bank, "ekonomika")
    add_row(make_quiz(slug="evropa"), bank, count=2, folder_id=str(ekonomika.pk))
    plan = plan_into(bank, row("ekonomika"), row("ekonomika/fondy"))
    assert import_structure.short_rows(plan, bank) == []


def test_short_rows_follow_tag_difficulty_and_languages():
    bank = make_bank()
    quiz = make_quiz(slug="evropa", locales=("cs", "en"))
    add_row(quiz, bank, count=1, difficulty="hard")
    add_row(quiz, bank, count=2, tag="EU")
    plan = plan_into(bank, row("", tags="EU,easy"), {**ONLY_CS, "tags": "EU"})
    short = import_structure.short_rows(plan, bank)
    assert [(item.difficulty, item.tag, item.available, item.wanted) for item in short] == [
        (banks.level_label("hard"), "", 0, 1),
        ("", "EU", 1, 2),
    ]


def test_archived_quizzes_are_left_out_and_a_published_quiz_counts():
    bank = make_bank()
    for _number in range(5):
        add_bank_question(bank)
    archived = make_quiz(slug="archiv")
    add_row(archived, bank, count=5)
    authoring.archive_quiz(archived, admin_id=ADMIN_ID)
    published = make_quiz(slug="hraje")
    add_row(published, bank, count=5)
    authoring.publish(published, admin_id=ADMIN_ID)
    short = import_structure.short_rows(plan_into(bank, row("")), bank)
    assert [item.quiz for item in short] == ["hraje"]


def test_a_row_whose_folder_is_gone_counts_nothing():
    bank = make_bank()
    quiz = make_quiz(slug="evropa")
    gone = folder(bank, "pryč")
    add_row(quiz, bank, count=1, folder_id=str(gone.pk))
    gone.delete()
    short = import_structure.short_rows(plan_into(bank, row("pryč")), bank)
    assert [(item.available, item.wanted) for item in short] == [(0, 1)]

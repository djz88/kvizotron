"""What the writer produces is safe in a spreadsheet and reads back unchanged."""

import io
import zipfile

import pytest

from app.contracts import ExportTable
from app.providers.csv_io.provider import CsvExporter
from app.providers.csv_io.reader import parse_csv
from app.providers.csv_io.writer import protect, write_csv, write_table


def written_cell(text):
    return protect(text)


def read_back(text):
    data = write_csv(["a"], [{"a": text}])
    _columns, rows = parse_csv(data)
    return rows[0].cells["a"]


@pytest.mark.parametrize("text", ["=1+1", "+a", "-a", "@a", "\tx", "\rx", "'=1", "''+x", "'plain"])
def test_formula_protection_is_safe_and_lossless(text):
    cell = written_cell(text)
    assert cell[0] not in "=+-@\t\r"
    assert read_back(text) == text


def test_ordinary_text_is_not_touched():
    assert protect("Otázka") == "Otázka"
    assert read_back("řádek 1\nřádek 2") == "řádek 1\nřádek 2"


def test_no_files_gives_csv_with_bom():
    exported = CsvExporter().write(["a"], [{"a": "č"}], {})
    assert exported.extension == "csv"
    assert exported.data.startswith(b"\xef\xbb\xbf")
    assert "text/csv" in exported.content_type


def test_files_give_zip_with_csv_at_top():
    exported = CsvExporter().write(["a"], [{"a": "1"}], {"images/x.webp": b"data"})
    assert exported.extension == "zip"
    with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
        assert sorted(archive.namelist()) == ["images/x.webp", "questions.csv"]
        assert archive.read("images/x.webp") == b"data"


def test_missing_cell_is_written_blank():
    assert parse_csv(write_csv(["a", "b"], [{"a": "1"}]))[1][0].cells == {"a": "1", "b": ""}


def table_text(table):
    out = io.StringIO(newline="")
    write_table(table, out)
    return out.getvalue()


def test_table_is_semicolon_bom_crlf():
    """AC-102."""
    table = ExportTable(
        name="runs",
        columns=["run", "score"],
        headers=["Běh", "Skóre"],
        rows=[{"run": "1", "score": "2,5"}],
    )
    text = table_text(table)
    assert text.startswith("﻿Běh;Skóre\r\n")
    assert text == "﻿Běh;Skóre\r\n1;2,5\r\n"


def test_numeric_exemption_only_in_numeric_columns():
    """AC-102."""
    table = ExportTable(
        name="t",
        columns=["name", "score"],
        headers=["Name", "Score"],
        rows=[
            {"name": "-1", "score": "-1,5"},
            {"name": "=HYPERLINK(1)", "score": "=1"},
        ],
        numeric=frozenset({"score"}),
    )
    lines = table_text(table).split("\r\n")
    assert lines[1] == "'-1;-1,5"
    assert lines[2] == "'=HYPERLINK(1);'=1"

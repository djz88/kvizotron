"""Files that are safe to open in a spreadsheet, and that read back unchanged."""

import csv
import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from typing import IO

from app.contracts import ExportTable

DANGEROUS = re.compile(r"'*[=+\-@\t\r]")
BOM = "﻿"
NUMBER = re.compile(r"-?\d+([.,]\d+)?", re.ASCII)


def protect(cell: str) -> str:
    """A spreadsheet runs such a cell as a formula. Quotes count, so that it is reversible."""
    return f"'{cell}" if DANGEROUS.match(cell) else cell


def write_csv(columns: Sequence[str], rows: Sequence[Mapping[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    buffer.write(BOM)
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([protect(row.get(column, "")) for column in columns])
    return buffer.getvalue().encode("utf-8")


def write_table(table: ExportTable, out: IO[str]) -> None:
    """Results for a spreadsheet: semicolons, BOM, CRLF. A plain number in a numeric column
    stays a number; every other cell is protected."""
    out.write(BOM)
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow([protect(header) for header in table.headers])
    for row in table.rows:
        cells = []
        for column in table.columns:
            value = row.get(column, "")
            numeric = column in table.numeric and NUMBER.fullmatch(value)
            cells.append(value if numeric else protect(value))
        writer.writerow(cells)


def write_zip(csv_data: bytes, files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("questions.csv", csv_data)
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()

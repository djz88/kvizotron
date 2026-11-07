"""Files that are safe to open in a spreadsheet, and that read back unchanged."""

import csv
import io
import re
import zipfile
from collections.abc import Mapping, Sequence

DANGEROUS = re.compile(r"'*[=+\-@\t\r]")
BOM = "﻿"


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


def write_zip(csv_data: bytes, files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("questions.csv", csv_data)
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()

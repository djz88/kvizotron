"""Reading an uploaded CSV or ZIP. Nothing here trusts the file, and nothing is unpacked to disk."""

import csv
import io
import re
import zipfile
import zlib
from pathlib import Path

from django.utils.translation import gettext as _

from app.contracts import CsvRow, ImportRefused, ParsedFile
from app.providers.csv_io import limits

PROTECTED = re.compile(r"'+[=+\-@\t\r]")
ZIP_START = b"PK\x03\x04"
ENCRYPTED = 0x1
IGNORED_PREFIXES = ("__MACOSX/",)
IGNORED_NAMES = (".DS_Store", "Thumbs.db")


READ_ERRORS = (zipfile.BadZipFile, zlib.error, OSError, EOFError, NotImplementedError, RuntimeError)


def _unprotected(cell: str) -> str:
    return cell[1:] if PROTECTED.match(cell) else cell


def _delimiter(text: str) -> str:
    header = text.split("\n", 1)[0]
    return ";" if header.count(";") > header.count(",") else ","


def _columns(header: list[str]) -> list[str]:
    columns = [name.strip().lower() for name in header]
    named = [name for name in columns if name]
    if not named:
        raise ImportRefused(_("The file has no column names."))
    if len(set(named)) != len(named):
        raise ImportRefused(_("A column name is used twice."))
    return columns


def _row(number: int, columns: list[str], cells: list[str]) -> CsvRow:
    extra = cells[len(columns) :]
    named = [
        (name, cells[index] if index < len(cells) else "")
        for index, name in enumerate(columns)
        if name
    ]
    unnamed = [cells[i] for i, name in enumerate(columns) if not name and i < len(cells)]
    has_extra = any(cell.strip() for cell in (*extra, *unnamed))
    return CsvRow(
        number=number,
        cells={name: _unprotected(cell) for name, cell in named},
        error=_("This row has more cells than the file has columns.") if has_extra else None,
    )


def parse_csv(data: bytes) -> tuple[list[str], list[CsvRow]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportRefused(_("The file is not in UTF-8. Save it as CSV UTF-8.")) from exc
    if "\0" in text:
        raise ImportRefused(_("The file could not be read as CSV."))
    rows: list[CsvRow] = []
    columns: list[str] | None = None
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=_delimiter(text), strict=True)
        number = 0
        for cells in reader:
            if not cells:
                continue
            number += 1
            if columns is None:
                columns = _columns(cells)
                continue
            if len(rows) == limits.MAX_ROWS:
                raise ImportRefused(_("The file has more than 2000 rows."))
            rows.append(_row(number, columns, cells))
    except csv.Error as exc:
        raise ImportRefused(_("The file could not be read as CSV.")) from exc
    if columns is None:
        raise ImportRefused(_("The file is empty."))
    return [name for name in columns if name], rows


def _usable_entries(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return [
        info
        for info in archive.infolist()
        if not info.is_dir()
        and not info.filename.startswith(IGNORED_PREFIXES)
        and Path(info.filename).name not in IGNORED_NAMES
    ]


def _bounded(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """Reading stops at the limit whatever the archive declares about itself."""
    with archive.open(info) as entry:
        data = entry.read(limit + 1)
    if len(data) > limit:
        raise ImportRefused(
            _("A file in the archive is too large: %(name)s") % {"name": info.filename}
        )
    return data


def _open_checked(path: Path) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise ImportRefused(_("The archive could not be read.")) from exc
    infos = archive.infolist()
    too_large = sum(info.file_size for info in infos) > limits.MAX_ZIP_UNPACKED_BYTES
    if len(infos) > limits.MAX_ZIP_ENTRIES or too_large:
        archive.close()
        raise ImportRefused(_("The archive holds too many files or too much data."))
    if any(info.flag_bits & ENCRYPTED for info in infos):
        archive.close()
        raise ImportRefused(_("The archive is encrypted."))
    return archive


def _csv_entry(entries: list[zipfile.ZipInfo]) -> zipfile.ZipInfo:
    found = [
        info
        for info in entries
        if "/" not in info.filename and info.filename.lower().endswith(".csv")
    ]
    if len(found) != 1:
        raise ImportRefused(_("The archive must hold exactly one CSV file at its top level."))
    return found[0]


def parse_file(path: Path) -> ParsedFile:
    with path.open("rb") as file:
        is_zip = file.read(len(ZIP_START)) == ZIP_START
    if not is_zip:
        if path.stat().st_size > limits.MAX_CSV_BYTES:
            raise ImportRefused(_("The CSV file is larger than 5 MB."))
        columns, rows = parse_csv(path.read_bytes())
        return ParsedFile(columns, rows, frozenset())
    with _open_checked(path) as archive:
        entries = _usable_entries(archive)
        found = _csv_entry(entries)
        try:
            data = _bounded(archive, found, limits.MAX_CSV_BYTES)
        except READ_ERRORS as exc:
            raise ImportRefused(_("The archive could not be read.")) from exc
        columns, rows = parse_csv(data)
        names = frozenset(info.filename for info in entries if info is not found)
    return ParsedFile(columns, rows, names)


def read_entry(path: Path, name: str) -> bytes:
    with _open_checked(path) as archive:
        for info in _usable_entries(archive):
            if info.filename == name:
                try:
                    return _bounded(archive, info, limits.MAX_IMAGE_BYTES)
                except READ_ERRORS as exc:
                    raise ImportRefused(_("The archive could not be read.")) from exc
    raise ImportRefused(_("The archive has no file named %(name)s.") % {"name": name})

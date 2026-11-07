"""Reading what an admin uploads: spreadsheets of all kinds, and files meant to do harm."""

import io
import struct
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from app.contracts import ImportJobGone, ImportRefused
from app.providers.csv_io import limits
from app.providers.csv_io.models import ImportJobRecord
from app.providers.csv_io.provider import CsvImporter
from app.providers.csv_io.reader import parse_csv

pytestmark = pytest.mark.django_db
TARGET = {"kind": "new_quiz", "id": ""}
ADMIN = "admin-a"
PLAIN = "schema_version,prompt_cs\n1,Otázka\n".encode()


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


@pytest.fixture
def importer():
    return CsvImporter()


def zip_of(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def begin(importer, data, admin=ADMIN):
    return importer.begin(admin, TARGET, [data])


def test_plain_csv():
    columns, rows = parse_csv(PLAIN)
    assert columns == ["schema_version", "prompt_cs"]
    assert rows[0].cells == {"schema_version": "1", "prompt_cs": "Otázka"}
    assert rows[0].number == 2


def test_excel_semicolons_bom_crlf_and_quoted_line_break_read_the_same():
    excel = '﻿a;b\r\n1;"řádek\r\ndruhý"\r\n2;x\r\n'.encode()
    plain = 'a,b\n1,"řádek\r\ndruhý"\n2,x\n'.encode()
    assert parse_csv(excel) == parse_csv(plain)
    assert parse_csv(excel)[1][1].number == 3


def test_comma_inside_semicolon_file_stays_in_its_cell():
    _columns, rows = parse_csv(b"a;b\n1,5;x\n")
    assert rows[0].cells["a"] == "1,5"


def test_other_encoding_refused_saying_csv_utf8():
    with pytest.raises(ImportRefused, match="UTF-8"):
        parse_csv("a,b\nč,ř\n".encode("cp1250"))


def test_header_is_lowercased_stripped_and_duplicate_refused():
    assert parse_csv(b" Prompt_CS ,B\n1,2\n")[0] == ["prompt_cs", "b"]
    with pytest.raises(ImportRefused):
        parse_csv(b"a,A\n1,2\n")


def test_empty_file_refused():
    with pytest.raises(ImportRefused):
        parse_csv(b"")


def test_row_with_too_many_cells_has_error_and_short_row_gets_blanks():
    _columns, rows = parse_csv(b"a,b\n1,2,3\n1\n")
    assert rows[0].error
    assert rows[1].error is None
    assert rows[1].cells == {"a": "1", "b": ""}


def test_spreadsheet_trailing_empty_columns_are_ignored():
    columns, rows = parse_csv(b"a;b;;\n1;2;;\n")
    assert columns == ["a", "b"]
    assert rows[0].error is None


def test_blank_lines_are_skipped():
    assert len(parse_csv(b"a\n\n1\n\n")[1]) == 1


def test_csv_over_5_mb_refused(importer):
    with pytest.raises(ImportRefused):
        begin(importer, b"a\n" + b"x" * limits.MAX_CSV_BYTES)


def test_over_2000_rows_refused():
    with pytest.raises(ImportRefused, match="2000"):
        parse_csv(b"a\n" + b"1\n" * (limits.MAX_ROWS + 1))
    assert len(parse_csv(b"a\n" + b"1\n" * limits.MAX_ROWS)[1]) == limits.MAX_ROWS


@pytest.mark.parametrize(
    "data", [b'a,b\n"x,1\n', b"a,b\n1\x00,2\n", b"a\n" + b"x" * 200_000 + b"\n"]
)
def test_unbalanced_nul_or_huge_cell_refused_not_a_server_error(data):
    with pytest.raises(ImportRefused):
        parse_csv(data)


def test_protective_character_removed_on_read():
    assert parse_csv(b"a\n'=1\n")[1][0].cells["a"] == "=1"
    assert parse_csv(b"a\n''=1\n")[1][0].cells["a"] == "'=1"
    assert parse_csv(b"a\n'plain\n")[1][0].cells["a"] == "'plain"


def test_zip_reads_its_csv_and_lists_images(importer):
    job = begin(importer, zip_of({"q.csv": PLAIN, "images/a.png": b"A", "b.png": b"B"}))
    parsed = importer.read(job)
    assert parsed.columns == ["schema_version", "prompt_cs"]
    assert parsed.files == {"images/a.png", "b.png"}
    assert importer.read_image(job, "images/a.png") == b"A"


def test_read_image_of_an_unknown_name_refused(importer):
    job = begin(importer, zip_of({"q.csv": PLAIN}))
    with pytest.raises(ImportRefused):
        importer.read_image(job, "missing.png")


@pytest.mark.parametrize(
    "entries", [{"a.csv": PLAIN, "b.csv": PLAIN}, {"x.png": b"1"}, {"folder/a.csv": PLAIN}]
)
def test_zip_with_two_csvs_or_none_at_top_level_refused(importer, entries):
    with pytest.raises(ImportRefused):
        begin(importer, zip_of(entries))


def test_macos_metadata_entries_ignored(importer):
    job = begin(
        importer,
        zip_of({"q.csv": PLAIN, "__MACOSX/._q.csv": b"x", ".DS_Store": b"x", "folder/": b""}),
    )
    assert importer.read(job).files == frozenset()


def test_not_a_zip_or_corrupt_refused(importer):
    with pytest.raises(ImportRefused):
        begin(importer, b"PK\x03\x04 this is no archive")
    with pytest.raises(ImportRefused):
        begin(importer, zip_of({"q.csv": PLAIN})[:-30])


def test_encrypted_refused(importer):
    data = bytearray(zip_of({"q.csv": PLAIN}))
    central = data.index(b"PK\x01\x02")
    struct.pack_into("<H", data, central + 8, 1)  # flag bit 0: encrypted
    with pytest.raises(ImportRefused):
        begin(importer, bytes(data))


def test_zip_over_entry_limit_refused(importer, monkeypatch):
    monkeypatch.setattr(limits, "MAX_ZIP_ENTRIES", 2)
    with pytest.raises(ImportRefused):
        begin(importer, zip_of({"q.csv": PLAIN, "a": b"1", "b": b"2"}))


def test_zip_over_declared_size_refused_unread(importer, monkeypatch):
    monkeypatch.setattr(limits, "MAX_ZIP_UNPACKED_BYTES", 100)
    with pytest.raises(ImportRefused):
        begin(importer, zip_of({"q.csv": PLAIN, "a": b"0" * 1000}))


def test_upload_over_limit_stops_writing(importer, monkeypatch, media):
    monkeypatch.setattr(limits, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ImportRefused):
        importer.begin(ADMIN, TARGET, [b"12345678", b"12345678", b"never read"])
    assert not list((media / "imports").glob("*")) if (media / "imports").exists() else True
    assert not ImportJobRecord.objects.exists()


def test_zip_lying_about_its_size_stops_at_the_limit(importer):
    data = bytearray(zip_of({"q.csv": PLAIN, "a.png": b"0" * 5000}))
    first = data.index(b"PK\x01\x02")
    second = data.index(b"PK\x01\x02", first + 1)
    struct.pack_into("<I", data, second + 24, 10)  # declares 10 bytes, holds 5000
    job = begin(importer, bytes(data))
    with pytest.raises(ImportRefused):
        importer.read_image(job, "a.png")


def test_image_over_its_limit_refused(importer, monkeypatch):
    monkeypatch.setattr(limits, "MAX_IMAGE_BYTES", 10)
    job = begin(importer, zip_of({"q.csv": PLAIN, "a.png": b"0" * 100}))
    with pytest.raises(ImportRefused):
        importer.read_image(job, "a.png")


def test_zip_entry_with_traversal_name_writes_nothing_outside_job(
    importer, media, tmp_path_factory
):
    outside = tmp_path_factory.mktemp("outside")
    names = {"q.csv": PLAIN, "../../etc/x.png": b"X", f"{outside}/y.png": b"Y"}
    job = begin(importer, zip_of(names))
    parsed = importer.read(job)
    assert "../../etc/x.png" in parsed.files
    assert not any(outside.iterdir())
    written = [path for path in media.rglob("*") if path.is_file()]
    assert written == [Path(media) / "imports" / job]
    assert importer.read_image(job, "../../etc/x.png") == b"X"


def test_new_upload_replaces_that_admins_job_not_another_admins(importer, media):
    first = begin(importer, PLAIN)
    other = begin(importer, PLAIN, admin="admin-b")
    second = begin(importer, PLAIN)
    with pytest.raises(ImportJobGone):
        importer.job(first, ADMIN)
    assert importer.job(second, ADMIN).id == second
    assert importer.job(other, "admin-b").id == other
    assert not (media / "imports" / first).exists()


def test_expired_job_removed_on_next_begin_with_its_file(importer, media):
    old = begin(importer, PLAIN, admin="admin-b")
    ImportJobRecord.objects.filter(pk=old).update(expires_at=timezone.now() - timedelta(minutes=1))
    with pytest.raises(ImportJobGone):
        importer.job(old, "admin-b")
    begin(importer, PLAIN)
    assert not ImportJobRecord.objects.filter(pk=old).exists()
    assert not (media / "imports" / old).exists()


def test_job_lasts_24_hours(importer):
    job = begin(importer, PLAIN)
    record = ImportJobRecord.objects.get(pk=job)
    assert record.expires_at - record.created_at == pytest.approx(
        timedelta(hours=24), abs=timedelta(seconds=5)
    )


def test_job_of_other_admin_is_gone(importer):
    job = begin(importer, PLAIN)
    with pytest.raises(ImportJobGone):
        importer.job(job, "admin-b")
    with pytest.raises(ImportJobGone):
        importer.job("not-a-uuid", ADMIN)


def test_job_keeps_target_and_mapping(importer):
    job = importer.begin(ADMIN, {"kind": "bank", "id": "b1"}, [PLAIN])
    importer.set_mapping(job, {"x": "prompt_cs"})
    seen = importer.job(job, ADMIN)
    assert seen.target == {"kind": "bank", "id": "b1"}
    assert seen.mapping == {"x": "prompt_cs"}
    assert seen.report is None


def test_claim_is_true_once(importer):
    job = begin(importer, PLAIN)
    assert importer.claim(job) is True
    assert importer.claim(job) is False


def test_finish_removes_the_file_keeps_report(importer, media):
    job = begin(importer, PLAIN)
    importer.claim(job)
    importer.finish(job, {"added": 1})
    assert not (media / "imports" / job).exists()
    assert importer.job(job, ADMIN).report == {"added": 1}


def test_damaged_compressed_stream_is_refused_and_leaves_no_file(importer, media):
    data = bytearray(zip_of({"q.csv": PLAIN * 200}))
    start = 30 + len("q.csv")
    for offset in range(start + 2, start + 40):
        data[offset] ^= 0xFF
    with pytest.raises(ImportRefused):
        begin(importer, bytes(data))
    assert not list((media / "imports").iterdir())
    assert not ImportJobRecord.objects.exists()


def test_read_of_a_job_whose_file_is_gone(importer, media):
    job = begin(importer, PLAIN)
    (media / "imports" / job).unlink()
    with pytest.raises(ImportJobGone):
        importer.read(job)

from pathlib import Path

from app.domain.models import AppSetting
from tests.support.run import run


def test_the_file_database_has_the_production_options_and_the_schema(file_db, db):
    assert file_db.execute("PRAGMA journal_mode") == [("wal",)]
    file_db.execute("insert into app_setting (key, value_json) values ('probe', '1')")
    assert file_db.execute("select count(*) from app_setting where key='probe'") == [(1,)]
    assert not AppSetting.objects.filter(key="probe").exists(), "the default database is untouched"


def test_each_test_gets_its_own_file(file_db):
    assert file_db.execute("select count(*) from app_setting where key='probe'") == [(0,)]


def test_the_template_directory_is_removed_when_the_process_ends(tmp_path):
    result = run(
        "-c",
        "from tests.support import file_database\nprint(file_database._template().parent)",
        db=tmp_path / "unused.sqlite3",
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).name.startswith("kvz-file-db-")
    assert not Path(result.stdout.strip()).exists()

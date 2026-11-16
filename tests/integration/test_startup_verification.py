import pytest

from tests.support.modules import make_module
from tests.support.run import AUTH_TEST_SITE, DEMO_SITE, run, run_manage, run_python

IMPORT_WSGI = ("-c", "import app.wsgi")


def test_unmigrated_database_aborts_naming_migrate(tmp_path):
    result = run(*IMPORT_WSGI, db=tmp_path / "db.sqlite3")
    assert result.returncode != 0
    assert "manage.py migrate" in result.stderr


def test_module_without_applied_migrations_aborts(tmp_path):
    db = tmp_path / "db.sqlite3"
    assert run_manage("migrate", "--noinput", db=db).returncode == 0
    result = run(*IMPORT_WSGI, db=db, sites=[DEMO_SITE])
    assert result.returncode != 0
    assert "manage.py migrate" in result.stderr


def test_migrated_database_starts(tmp_path):
    db = tmp_path / "db.sqlite3"
    assert run_manage("migrate", "--noinput", db=db, sites=[DEMO_SITE]).returncode == 0
    result = run(*IMPORT_WSGI, db=db, sites=[DEMO_SITE])
    assert result.returncode == 0, result.stderr


def test_migrate_works_on_an_empty_database(tmp_path):
    result = run_manage("migrate", "--noinput", db=tmp_path / "db.sqlite3")
    assert result.returncode == 0, result.stderr


def test_modules_cli_lists_toggles_and_refuses(tmp_path):
    db = tmp_path / "db.sqlite3"
    sites = [DEMO_SITE]
    assert run_manage("migrate", "--noinput", db=db, sites=sites).returncode == 0

    assert run_manage("modules", "verify", db=db, sites=sites).returncode == 0
    listing = run_manage("modules", "list", db=db, sites=sites)
    assert "question.demo" in listing.stdout
    assert "enabled" in listing.stdout

    assert run_manage("modules", "disable", "question.demo", db=db, sites=sites).returncode == 0
    assert "disabled" in run_manage("modules", "list", db=db, sites=sites).stdout

    refused = run_manage("modules", "disable", "retention.local", db=db, sites=sites)
    assert refused.returncode != 0
    assert "retention.local" in refused.stderr
    assert "Traceback" not in refused.stderr

    locked = run_manage("modules", "disable", "flow.basic", db=db, sites=sites)
    assert locked.returncode != 0
    assert "flow.basic" in locked.stderr
    assert "Traceback" not in locked.stderr


def last_line(result):
    return result.stderr.strip().splitlines()[-1]


@pytest.mark.parametrize("broken_file", ["apps.py", "models.py"])
@pytest.mark.parametrize("command", [("manage.py", "check"), IMPORT_WSGI])
def test_failure_in_module_code_names_the_module(tmp_path, broken_file, command):
    package = make_module(tmp_path, "bad.code")
    (tmp_path / package / broken_file).write_text("import does_not_exist_anywhere\n")
    result = run(*command, db=tmp_path / "db.sqlite3", sites=[tmp_path])
    assert result.returncode != 0
    assert "bad.code" in last_line(result)
    assert "does_not_exist_anywhere" in last_line(result)


def test_missing_app_package_names_the_module(tmp_path):
    make_module(tmp_path, "bad.app", app="nope_missing.apps.X")
    result = run_manage("check", db=tmp_path / "db.sqlite3", sites=[tmp_path])
    assert result.returncode != 0
    assert "bad.app" in last_line(result)


def test_configuration_error_is_not_blamed_on_a_module(tmp_path):
    make_module(tmp_path, "good.mod")
    result = run_manage(
        "check", db=tmp_path / "db.sqlite3", sites=[tmp_path], env={"KVZ_SECRET_KEY": ""}
    )
    assert result.returncode != 0
    assert "KVZ_SECRET_KEY" in last_line(result)
    assert "good.mod" not in last_line(result)


@pytest.mark.parametrize("urls", ["nope_missing", "builtins"])
def test_broken_module_urls_stop_startup(tmp_path, urls):
    make_module(tmp_path, "bad.urls", urls=urls)
    result = run(*IMPORT_WSGI, db=tmp_path / "db.sqlite3", sites=[tmp_path])
    assert result.returncode != 0
    assert "bad.urls" in last_line(result)


def installation_status(module_id, **kwargs):
    result = run_python(
        "from app.kernel.models import PluginInstallation\n"
        f'print(PluginInstallation.objects.get(pk="{module_id}").status)',
        **kwargs,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def start_with_test_provider_installed(db):
    choice = {"sites": [AUTH_TEST_SITE], "env": {"KVZ_PROVIDER_AUTH": "auth.local"}}
    assert run_manage("migrate", "--noinput", db=db, **choice).returncode == 0
    started = run(*IMPORT_WSGI, db=db, **choice)
    assert started.returncode == 0, started.stderr
    return choice


def test_unselected_provider_is_inactive_not_missing(tmp_path):
    db = tmp_path / "db.sqlite3"
    choice = start_with_test_provider_installed(db)
    assert installation_status("auth.test", db=db, **choice) == "INACTIVE"
    assert installation_status("auth.local", db=db, **choice) == "INSTALLED"


def test_removed_module_is_missing(tmp_path):
    db = tmp_path / "db.sqlite3"
    start_with_test_provider_installed(db)
    started = run(*IMPORT_WSGI, db=db)
    assert started.returncode == 0, started.stderr
    assert installation_status("auth.test", db=db) == "MISSING"


def test_missing_parent_of_dotted_app_package_names_the_module(tmp_path):
    make_module(tmp_path, "bad.dotted", app="nope_parent.sub.apps.X")
    result = run_manage("check", db=tmp_path / "db.sqlite3", sites=[tmp_path])
    assert result.returncode != 0
    assert "bad.dotted" in last_line(result)


def test_database_from_a2_upgrades_and_starts(tmp_path):
    db = tmp_path / "db.sqlite3"
    assert run_manage("migrate", "kernel", "0001", "--noinput", db=db).returncode == 0
    upgraded = run_manage("migrate", "--noinput", db=db)
    assert upgraded.returncode == 0, upgraded.stderr
    started = run(*IMPORT_WSGI, db=db)
    assert started.returncode == 0, started.stderr

"""An operator must see failures: Django logs nothing by default with DEBUG off."""

from tests.support.run import run_python


def test_server_error_reaches_the_container_log(tmp_path):
    code = "import logging\nlogging.getLogger('django.request').error('request failed')"
    result = run_python(code, db=tmp_path / "db.sqlite3")
    assert "request failed" in result.stderr


def test_application_warning_reaches_the_container_log(tmp_path):
    code = "import logging\nlogging.getLogger('app.kernel.events').warning('handler failed')"
    result = run_python(code, db=tmp_path / "db.sqlite3")
    assert "handler failed" in result.stderr


def test_client_errors_do_not_fill_the_log(tmp_path):
    code = "import logging\nlogging.getLogger('django.request').warning('Not Found: /x')"
    result = run_python(code, db=tmp_path / "db.sqlite3")
    assert "Not Found" not in result.stderr

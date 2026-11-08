"""AC-89: one question at a time is the default only for a new installation."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = [("domain", "0014_results"), ("kernel", "0003_plugininstallation_inactive")]
AFTER = [("domain", "0015_navigation_default")]


@pytest.fixture(autouse=True)
def back_to_latest():
    """The next transactional test needs every migration, not the one this file stops at."""
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def stored(apps):
    setting = apps.get_model("domain", "AppSetting")
    row = setting.objects.filter(key="navigation_mode", quiz=None).first()
    return row.value_json if row else None


def test_existing_installation_keeps_all_at_once():
    old = migrate(BEFORE)
    old.get_model("domain", "Quiz").objects.create(
        slug="kviz", title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    assert stored(migrate(AFTER)) == "all_at_once"


def test_installation_with_only_an_admin_keeps_all_at_once():
    old = migrate(BEFORE)
    old.get_model("kernel", "AdminUser").objects.create(login="alice", password="x")
    assert stored(migrate(AFTER)) == "all_at_once"


def test_stored_global_value_is_left_alone():
    old = migrate(BEFORE)
    old.get_model("domain", "AppSetting").objects.create(
        key="navigation_mode", value_json="step_no_back"
    )
    old.get_model("kernel", "AdminUser").objects.create(login="alice", password="x")
    assert stored(migrate(AFTER)) == "step_no_back"


def test_fresh_installation_gets_step_back():
    migrate(BEFORE)
    assert stored(migrate(AFTER)) is None
    from app.domain import settings

    assert settings.resolve(settings.NAVIGATION_MODE) == "step_back"

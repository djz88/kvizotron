from decimal import Decimal

import pytest
from django.test import override_settings

from app.contracts import ScoreBreakdown
from app.kernel import lifecycle, registry
from app.kernel.errors import StartupError
from app.kernel.manifest import Manifest
from app.kernel.models import AuditEvent, PluginInstallation


class Scoring:
    id = "basic"
    version = "1.0.0"

    def label(self):
        return "Basic"

    def supports(self, question_type_id):
        return True

    def max_score(self, settings):
        return Decimal(1)

    def evaluate(self, grade, settings):
        return ScoreBreakdown(Decimal(1), Decimal(1), 1, {})


def manifest(module_id, kind="plugin", **fields):
    return Manifest(
        id=module_id,
        kind=kind,
        version="1.0.0",
        app="x.y",
        api_compatibility=">=1.0",
        settings=[],
        **fields,
    )


PLUGIN = manifest("plug.a", provides=["scoring_strategy", "cap_a"])
DEPENDENT = manifest("plug.b", requires=["cap_a"])
OPTIONAL_USER = manifest("plug.c", optional=["cap_a"])
PROVIDER = manifest("prov.auth", kind="provider", provides=["auth"])

CLI = {"actor_type": "cli", "actor_id": None}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(registry, "_ports", {})
    monkeypatch.setattr(lifecycle, "_usage_checks", [])
    monkeypatch.setattr(lifecycle, "_startup_checks", [])
    with override_settings(KVZ_MODULES=[PLUGIN, DEPENDENT, OPTIONAL_USER, PROVIDER]):
        registry.register("scoring_strategy", "basic", Scoring(), owner="plug.a")
        yield


def test_new_module_is_enabled_by_default(db):
    assert registry.is_enabled("plug.a")
    assert registry.keys("scoring_strategy") == ["basic"]


def test_disable_hides_port_and_keeps_it_for_existing_revisions(db):
    lifecycle.set_enabled("plug.b", False, **CLI)
    lifecycle.set_enabled("plug.a", False, **CLI)
    assert registry.keys("scoring_strategy") == []
    with pytest.raises(registry.ModuleDisabled):
        registry.get("scoring_strategy", "basic")
    assert isinstance(registry.get("scoring_strategy", "basic", include_disabled=True), Scoring)


def test_provider_cannot_be_toggled(db):
    with pytest.raises(lifecycle.NotToggleable, match="prov.auth"):
        lifecycle.set_enabled("prov.auth", False, **CLI)


def test_usage_check_blocks_disable(db):
    lifecycle.set_enabled("plug.b", False, **CLI)
    audit_rows = AuditEvent.objects.count()
    lifecycle.register_usage_check(lambda module_id: ["active quiz Pub"])
    with pytest.raises(lifecycle.ModuleInUse, match="active quiz Pub"):
        lifecycle.set_enabled("plug.a", False, **CLI)
    assert registry.is_enabled("plug.a")
    assert AuditEvent.objects.count() == audit_rows


def test_disable_blocked_while_enabled_module_requires_it(db):
    with pytest.raises(lifecycle.DependencyDisabled, match="plug.b"):
        lifecycle.set_enabled("plug.a", False, **CLI)
    assert registry.is_enabled("plug.a")


def test_optional_dependency_does_not_block_disable(db):
    lifecycle.set_enabled("plug.b", False, **CLI)
    lifecycle.set_enabled("plug.a", False, **CLI)
    assert not registry.is_enabled("plug.a")


def test_enable_blocked_while_dependency_disabled(db):
    lifecycle.set_enabled("plug.b", False, **CLI)
    lifecycle.set_enabled("plug.a", False, **CLI)
    with pytest.raises(lifecycle.DependencyDisabled, match="plug.a"):
        lifecycle.set_enabled("plug.b", True, **CLI)
    assert not registry.is_enabled("plug.b")


def test_toggle_writes_audit_event(db):
    lifecycle.set_enabled("plug.b", False, actor_type="admin", actor_id="admin-1")
    event = AuditEvent.objects.get()
    assert (event.action, event.entity_type, event.entity_id) == (
        "plugin.disabled",
        "plugin",
        "plug.b",
    )
    assert (event.actor_type, event.actor_id) == ("admin", "admin-1")
    assert event.pk.version == 7


def test_repeating_the_same_state_writes_no_audit_event(db):
    lifecycle.set_enabled("plug.b", True, **CLI)
    assert AuditEvent.objects.count() == 0


def test_state_and_audit_commit_together(db, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr(lifecycle.audit, "record", fail)
    with pytest.raises(RuntimeError):
        lifecycle.set_enabled("plug.b", False, **CLI)
    assert registry.is_enabled("plug.b")


def test_unknown_module_rejected(db):
    with pytest.raises(lifecycle.UnknownModule, match="nope"):
        lifecycle.set_enabled("nope", False, **CLI)


def test_verify_records_installed_and_missing_modules(db):
    PluginInstallation.objects.create(plugin_id="gone.mod", version="1", manifest_json={})
    lifecycle.verify_startup()
    assert PluginInstallation.objects.get(pk="gone.mod").status == "MISSING"
    assert PluginInstallation.objects.get(pk="plug.a").status == "INSTALLED"


def test_verify_keeps_disabled_state(db):
    lifecycle.set_enabled("plug.b", False, **CLI)
    lifecycle.verify_startup()
    assert not registry.is_enabled("plug.b")


def test_failing_startup_check_aborts_with_its_problem(db):
    lifecycle.register_startup_check(lambda: ["run 7 needs question type x"])
    with pytest.raises(StartupError, match="run 7 needs question type x"):
        lifecycle.verify_startup()


def test_verify_rejects_enabled_module_whose_dependency_is_disabled(db):
    PluginInstallation.objects.create(
        plugin_id="plug.a", version="1.0.0", manifest_json={}, enabled=False
    )
    with pytest.raises(StartupError, match=r"plug\.b.*cap_a"):
        lifecycle.verify_startup()

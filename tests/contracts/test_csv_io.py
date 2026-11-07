"""The CSV provider through its contracts."""

import pytest

from app.contracts import ExporterProvider, ImporterProvider
from app.kernel import registry
from app.kernel.discovery import installed_modules


@pytest.mark.django_db
def test_it_provides_both_ports():
    assert isinstance(registry.get("importer", "csv"), ImporterProvider)
    assert isinstance(registry.get("exporter", "csv"), ExporterProvider)


def test_manifest_has_settings_and_states_none():
    manifest = next(m for m in installed_modules() if m.id == "csv.io")
    assert manifest.settings == []
    assert set(manifest.provides) == {"importer", "exporter"}

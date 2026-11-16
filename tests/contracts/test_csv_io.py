"""The CSV provider through its contracts."""

import pytest

from app.contracts import ExporterProvider, ImporterProvider, ResultsExporterProvider
from app.kernel import registry
from app.kernel.discovery import installed_modules
from tests.contracts.results_exporter import ResultsExporterSuite


@pytest.mark.django_db
def test_it_provides_both_ports():
    assert isinstance(registry.get("importer", "csv"), ImporterProvider)
    assert isinstance(registry.get("exporter", "csv"), ExporterProvider)
    assert isinstance(registry.get("results_exporter", "csv"), ResultsExporterProvider)


def test_manifest_has_settings_and_states_none():
    manifest = next(m for m in installed_modules() if m.id == "csv.io")
    assert manifest.settings == []
    assert set(manifest.provides) == {"importer", "exporter", "results_exporter"}


@pytest.mark.django_db
def test_the_results_exporter_passes_its_suite(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    ResultsExporterSuite(registry.get("results_exporter", "csv")).run()

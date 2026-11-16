from django.apps import AppConfig


class CsvIoConfig(AppConfig):
    name = "app.providers.csv_io"
    label = "csv_io"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from app.kernel import registry

        from .provider import CsvExporter, CsvImporter
        from .results import CsvResultsExporter

        registry.register("importer", CsvImporter.id, CsvImporter(), "csv.io")
        registry.register("exporter", CsvExporter.id, CsvExporter(), "csv.io")
        registry.register("results_exporter", CsvResultsExporter.id, CsvResultsExporter(), "csv.io")

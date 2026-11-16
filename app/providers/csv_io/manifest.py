def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "csv.io",
    "name": _("CSV import and export"),
    "description": _("Questions and results in CSV files."),
    "kind": "provider",
    "version": "1.0.0",
    "app": "app.providers.csv_io.apps.CsvIoConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["importer", "exporter", "results_exporter"],
    # Limits are constants: they guard the server and belong to no quiz (ADR-0045).
    "settings": [],
}

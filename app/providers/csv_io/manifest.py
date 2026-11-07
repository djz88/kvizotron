MANIFEST = {
    "id": "csv.io",
    "kind": "provider",
    "version": "1.0.0",
    "app": "app.providers.csv_io.apps.CsvIoConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["importer", "exporter"],
    # Limits are constants: they guard the server and belong to no quiz (ADR-0045).
    "settings": [],
}

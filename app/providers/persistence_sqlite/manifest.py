def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "persistence.sqlite",
    "name": _("Database"),
    "description": _("Stores everything in SQLite."),
    "kind": "provider",
    "version": "1.0.0",
    "app": "app.providers.persistence_sqlite.apps.PersistenceSqliteConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["persistence"],
    "persistence": "app.providers.persistence_sqlite.provider:SqliteProvider",
    "settings": [],
}

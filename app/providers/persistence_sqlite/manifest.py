MANIFEST = {
    "id": "persistence.sqlite",
    "kind": "provider",
    "version": "1.0.0",
    "app": "app.providers.persistence_sqlite.apps.PersistenceSqliteConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["persistence"],
    "persistence": "app.providers.persistence_sqlite.provider:SqliteProvider",
    "settings": [],
}

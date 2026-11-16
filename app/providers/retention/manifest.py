def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "retention.local",
    "name": _("Deletion trail"),
    "description": _("Records every deletion of a run's data."),
    "kind": "provider",
    "version": "1.0.0",
    "app": "app.providers.retention.apps.RetentionConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["retention"],
    # The hourly interval and the warning period are constants, and periods are per run.
    "settings": [],
}

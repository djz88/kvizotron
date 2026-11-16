def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "auth.local",
    "name": _("Admin login"),
    "description": _("Accounts of the administrators."),
    "kind": "provider",
    "version": "1.0.0",
    "app": "app.providers.auth_local.apps.AuthLocalConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["auth"],
    "auth_backend": "app.providers.auth_local.backends.LocalBackend",
    "settings": [],
}

MANIFEST = {
    "id": "auth.local",
    "kind": "provider",
    "version": "1.0.0",
    "app": "app.providers.auth_local.apps.AuthLocalConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["auth"],
    "auth_backend": "app.providers.auth_local.backends.LocalBackend",
    "settings": [],
}

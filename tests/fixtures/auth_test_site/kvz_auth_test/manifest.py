MANIFEST = {
    "id": "auth.test",
    "kind": "provider",
    "version": "1.0.0",
    "app": "kvz_auth_test.apps.AuthTestConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["auth"],
    "auth_backend": "kvz_auth_test.backends.TokenBackend",
    "settings": [],
}

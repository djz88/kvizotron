from app.kernel.discovery import load_modules


def test_installed_project_provides_required_modules():
    assert {"persistence.sqlite", "auth.local"} <= {module.id for module in load_modules({})}

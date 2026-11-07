"""Puts a fake installed module on disk; importlib.metadata finds it through sys.path."""

import uuid
from pathlib import Path


def make_module(
    root: Path,
    module_id: str,
    *,
    source: str | None = None,
    apps_body: str = "",
    **manifest_overrides: object,
) -> str:
    """Write a package with manifest, AppConfig and entry point. Returns the package name."""
    # A unique name per call: Python caches imported modules across tests.
    package = f"kvzt_{module_id.replace('.', '_')}_{uuid.uuid4().hex[:8]}"
    manifest = {
        "id": module_id,
        "kind": "plugin",
        "version": "1.0.0",
        "app": f"{package}.apps.Cfg",
        "api_compatibility": ">=1.0,<2.0",
        "settings": [],
    } | manifest_overrides
    package_dir = root / package
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")
    (package_dir / "manifest.py").write_text(source or f"MANIFEST = {manifest!r}\n")
    (package_dir / "apps.py").write_text(
        f"from django.apps import AppConfig\n\n\nclass Cfg(AppConfig):\n    name = {package!r}\n"
        + apps_body
    )
    dist_info = root / f"{package}-1.0.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {package}\nVersion: 1.0.0\n")
    (dist_info / "entry_points.txt").write_text(
        f"[kvizotron.modules]\n{module_id} = {package}.manifest:MANIFEST\n"
    )
    return package

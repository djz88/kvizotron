"""Django setup that says which module broke it."""

import traceback
from importlib.util import find_spec
from pathlib import Path

import django
from django.conf import settings

from app.kernel.errors import StartupError


def setup() -> None:
    try:
        django.setup()
    except StartupError:
        raise
    except Exception as exc:
        module_id = _culprit(exc)
        if module_id is None:
            raise
        raise StartupError(
            f"Module {module_id}: failed to load: {type(exc).__name__}: {exc}"
        ) from exc


def _culprit(exc: Exception) -> str | None:
    if not settings.configured:  # the settings themselves failed, no module is involved
        return None
    frames = [Path(frame.filename) for frame in traceback.extract_tb(exc.__traceback__)]
    missing = getattr(exc, "name", None) or ""
    for module in settings.KVZ_MODULES:
        # Own providers share the top-level package "app" with the kernel.
        package = module.app.rsplit(".", 2)[0]
        if missing == package or missing.startswith(f"{package}."):
            return module.id
        if missing and package.startswith(f"{missing}."):
            return module.id
        try:
            spec = find_spec(package)
        except ImportError:  # another module's parent package is missing too
            continue
        locations = (spec.submodule_search_locations or []) if spec else []
        roots = [Path(location) for location in locations]
        if any(root in frame.parents for root in roots for frame in frames):
            return module.id
    return None

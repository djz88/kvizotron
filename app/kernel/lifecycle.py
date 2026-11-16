"""Enabling and disabling plugins, and verification before the application serves requests."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.urls import get_resolver
from django.utils import translation
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

from app.contracts import AuthenticationProvider
from app.kernel import audit, registry
from app.kernel.discovery import installed_modules
from app.kernel.errors import StartupError
from app.kernel.manifest import Manifest
from app.kernel.models import PluginInstallation


class LifecycleError(Exception):
    """A refused change of a module's state; the message explains why."""


class UnknownModule(LifecycleError):
    pass


class NotToggleable(LifecycleError):
    pass


class ModuleInUse(LifecycleError):
    pass


class DependencyDisabled(LifecycleError):
    pass


class ModuleLocked(LifecycleError):
    pass


@dataclass(frozen=True)
class Blocker:
    """One reason a module cannot change state. `target` means nothing to the kernel."""

    kind: Literal["provider", "locked", "in_use", "dependency"]
    text: str
    target: tuple[str, str] | None = None


_usage_checks: list[Callable[[str], list[Blocker]]] = []
_startup_checks: list[Callable[[], list[str]]] = []


def register_usage_check(check: Callable[[str], list[Blocker]]) -> None:
    """check(module_id) returns the reasons why the module cannot be disabled now."""
    _usage_checks.append(check)


def register_startup_check(check: Callable[[], list[str]]) -> None:
    """check() returns the problems that must stop the application from starting."""
    _startup_checks.append(check)


def blockers(module_id: str, enabled: bool) -> list[Blocker]:
    """Why the module cannot move to `enabled` now, in the active language; empty when it can."""
    module = _module(module_id)
    if module.kind != "plugin":
        text = _("Provider %(module)s cannot be toggled, it changes on restart")
        return [Blocker("provider", text % {"module": module_id})]
    if registry.is_enabled(module_id) == enabled:
        return []
    return _enable_blockers(module) if enabled else _disable_blockers(module)


def set_enabled(module_id: str, enabled: bool, *, actor_type: str, actor_id: str | None) -> None:
    module = _module(module_id)
    with translation.override("en"):  # the exception ends in a log or on the command line
        found = blockers(module_id, enabled)
    if found:
        raise _refusal(module_id, found)
    if registry.is_enabled(module_id) == enabled:
        return
    with transaction.atomic():
        PluginInstallation.objects.update_or_create(
            pk=module_id, defaults=_row(module) | {"enabled": enabled}
        )
        audit.record(
            actor_type=actor_type,
            actor_id=actor_id,
            action="plugin.enabled" if enabled else "plugin.disabled",
            entity_type="plugin",
            entity_id=module_id,
        )


def verify_startup() -> None:
    """Stop the application if the database or the installed modules are not ready."""
    _check_auth_backends()
    _check_urls()
    _check_migrated()
    _sync_installations()
    problems = _dependency_problems()
    problems += [problem for check in _startup_checks for problem in check()]
    if problems:
        raise StartupError("Startup verification failed: " + "; ".join(problems))


def _module(module_id: str) -> Manifest:
    for module in settings.KVZ_MODULES:
        if module.id == module_id:
            return module
    raise UnknownModule(f"Module {module_id} is not installed")


def _row(module: Manifest) -> dict[str, object]:
    return {
        "version": module.version,
        "manifest_json": module.model_dump(mode="json"),
        "status": PluginInstallation.Status.INSTALLED,
    }


def _enabled_providers(capability: str, excluding: str | None = None) -> list[str]:
    return [
        m.id
        for m in settings.KVZ_MODULES
        if capability in m.provides and m.id != excluding and registry.is_enabled(m.id)
    ]


def _enable_blockers(module: Manifest) -> list[Blocker]:
    found = []
    for capability in module.requires:
        if not _enabled_providers(capability):
            providers = [m.id for m in settings.KVZ_MODULES if capability in m.provides]
            text = _("Module %(module)s requires %(capability)s; enable one of: %(providers)s")
            values = {
                "module": module.id,
                "capability": capability,
                "providers": ", ".join(providers),
            }
            found.append(Blocker("dependency", text % values))
    return found


def _disable_blockers(module: Manifest) -> list[Blocker]:
    found = [reason for check in _usage_checks for reason in check(module.id)]
    if module.always_on:
        text = _("The application cannot work without module %(module)s")
        found.append(Blocker("locked", text % {"module": module.id}))
    for other in settings.KVZ_MODULES:
        if other.id == module.id or not registry.is_enabled(other.id):
            continue
        for capability in sorted(set(other.requires) & set(module.provides)):
            if not _enabled_providers(capability, excluding=module.id):
                text = _("Module %(module)s provides %(capability)s required by %(other)s")
                values = {"module": module.id, "capability": capability, "other": other.id}
                found.append(Blocker("dependency", text % values))
    return found


def _refusal(module_id: str, found: list[Blocker]) -> LifecycleError:
    in_use = [blocker.text for blocker in found if blocker.kind == "in_use"]
    if in_use:
        return ModuleInUse(f"Module {module_id} is in use: " + "; ".join(in_use))
    errors = {
        "provider": NotToggleable,
        "locked": ModuleLocked,
        "dependency": DependencyDisabled,
    }
    return errors[found[0].kind](found[0].text)


def _dependency_problems() -> list[str]:
    """A module installed while its dependency is disabled never went through set_enabled."""
    return [
        f"enabled module {module.id} requires {capability}, whose providers are all disabled"
        for module in settings.KVZ_MODULES
        if registry.is_enabled(module.id)
        for capability in module.requires
        if not _enabled_providers(capability)
    ]


def _check_auth_backends() -> None:
    for module in settings.KVZ_MODULES:
        if "auth" not in module.provides or not module.auth_backend:
            continue
        try:
            backend = import_string(module.auth_backend)()
        except Exception as exc:
            raise StartupError(
                f"Module {module.id}: cannot load {module.auth_backend}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(backend, AuthenticationProvider):
            raise StartupError(
                f"Module {module.id}: {module.auth_backend} is not an AuthenticationProvider"
            )


def _check_urls() -> None:
    """Routes load on the first request; a broken module must stop the start, not answer 500."""
    for module in settings.KVZ_MODULES:
        if not module.urls:
            continue
        try:
            get_resolver(module.urls).url_patterns  # noqa: B018
        except Exception as exc:
            raise StartupError(
                f"Module {module.id}: cannot load urls {module.urls}: {type(exc).__name__}: {exc}"
            ) from exc


def _check_migrated() -> None:
    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except DatabaseError as exc:
        raise StartupError(
            f"Database is not ready ({type(exc).__name__}); run: manage.py migrate"
        ) from exc
    if pending:
        raise StartupError(
            f"Database has {len(pending)} unapplied migrations; run: manage.py migrate"
        )


def _sync_installations() -> None:
    active = {m.id for m in settings.KVZ_MODULES}
    installed = installed_modules()
    with transaction.atomic():
        for module in settings.KVZ_MODULES:
            PluginInstallation.objects.update_or_create(pk=module.id, defaults=_row(module))
        for module in installed:
            if module.id not in active:
                PluginInstallation.objects.update_or_create(
                    pk=module.id,
                    defaults=_row(module) | {"status": PluginInstallation.Status.INACTIVE},
                )
        PluginInstallation.objects.exclude(pk__in=active | {m.id for m in installed}).update(
            status=PluginInstallation.Status.MISSING
        )

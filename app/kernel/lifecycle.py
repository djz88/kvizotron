"""Enabling and disabling plugins, and verification before the application serves requests."""

from collections.abc import Callable

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.urls import get_resolver
from django.utils.module_loading import import_string

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


_usage_checks: list[Callable[[str], list[str]]] = []
_startup_checks: list[Callable[[], list[str]]] = []


def register_usage_check(check: Callable[[str], list[str]]) -> None:
    """check(module_id) returns the reasons why the module cannot be disabled now."""
    _usage_checks.append(check)


def register_startup_check(check: Callable[[], list[str]]) -> None:
    """check() returns the problems that must stop the application from starting."""
    _startup_checks.append(check)


def set_enabled(module_id: str, enabled: bool, *, actor_type: str, actor_id: str | None) -> None:
    module = _module(module_id)
    if module.kind != "plugin":
        raise NotToggleable(f"Provider {module_id} cannot be toggled, it changes on restart")
    if registry.is_enabled(module_id) == enabled:
        return
    if enabled:
        _check_can_enable(module)
    else:
        _check_can_disable(module)
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


def _check_can_enable(module: Manifest) -> None:
    for capability in module.requires:
        if not _enabled_providers(capability):
            providers = [m.id for m in settings.KVZ_MODULES if capability in m.provides]
            raise DependencyDisabled(
                f"Module {module.id} requires {capability}; enable one of: {', '.join(providers)}"
            )


def _check_can_disable(module: Manifest) -> None:
    reasons = [reason for check in _usage_checks for reason in check(module.id)]
    if reasons:
        raise ModuleInUse(f"Module {module.id} is in use: " + "; ".join(reasons))
    for other in settings.KVZ_MODULES:
        if other.id == module.id or not registry.is_enabled(other.id):
            continue
        for capability in set(other.requires) & set(module.provides):
            if not _enabled_providers(capability, excluding=module.id):
                raise DependencyDisabled(
                    f"Module {module.id} provides {capability} required by {other.id}"
                )


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

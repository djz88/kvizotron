"""Finds installed modules. Runs while settings load, so it must not import Django."""

import os
from collections.abc import Mapping
from graphlib import CycleError, TopologicalSorter
from importlib import import_module
from importlib.metadata import entry_points

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import ValidationError

from app import contracts
from app.kernel.errors import StartupError
from app.kernel.manifest import Manifest

GROUP = "kvizotron.modules"


def load_modules(env: Mapping[str, str] | None = None) -> list[Manifest]:
    """Return the active modules in dependency order, or raise StartupError."""
    modules = installed_modules()
    _check_kinds(modules)
    active = _select_providers(modules, os.environ if env is None else env)
    _check_required(active)
    _check_compatibility(active)
    return _in_dependency_order(active)


def load_persistence(modules: list[Manifest]) -> contracts.PersistenceProvider:
    """Build the persistence provider of the active modules, or raise StartupError."""
    module = next((m for m in modules if "persistence" in m.provides), None)
    if module is None or module.persistence is None:
        raise StartupError("No persistence provider is active")
    try:
        path, _, name = module.persistence.partition(":")
        provider = getattr(import_module(path), name)()
    except Exception as exc:
        raise StartupError(
            f"Module {module.id}: cannot load {module.persistence}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(provider, contracts.PersistenceProvider):
        raise StartupError(f"Module {module.id}: {module.persistence} is not a PersistenceProvider")
    return provider


def installed_modules() -> list[Manifest]:
    """Every installed module, including providers that are not selected."""
    modules: dict[str, Manifest] = {}
    for entry in sorted(entry_points(group=GROUP), key=lambda e: e.name):
        try:
            manifest = Manifest.model_validate(entry.load())
        except ValidationError as exc:
            raise StartupError(f"Module {entry.name}: invalid manifest: {exc}") from exc
        except Exception as exc:
            raise StartupError(
                f"Module {entry.name}: failed to load: {type(exc).__name__}: {exc}"
            ) from exc
        if manifest.id in modules:
            raise StartupError(f"Module id {manifest.id} is installed more than once")
        modules[manifest.id] = manifest
    return list(modules.values())


def _check_kinds(modules: list[Manifest]) -> None:
    for module in modules:
        infrastructure = contracts.EXACTLY_ONE & set(module.provides)
        if infrastructure and module.kind != "provider":
            raise StartupError(
                f"Module {module.id}: {sorted(infrastructure)} can only be provided by a provider"
            )
        if "persistence" in module.provides and not module.persistence:
            raise StartupError(f"Module {module.id}: providing persistence requires `persistence`")
        if "auth" in module.provides and not module.auth_backend:
            raise StartupError(f"Module {module.id}: providing auth requires `auth_backend`")


def _select_providers(modules: list[Manifest], env: Mapping[str, str]) -> list[Manifest]:
    excluded: set[str] = set()
    for capability in sorted(contracts.EXACTLY_ONE):
        candidates = [m.id for m in modules if capability in m.provides]
        variable = f"KVZ_PROVIDER_{capability.upper()}"
        wanted = env.get(variable)
        if wanted:
            if wanted not in candidates:
                raise StartupError(f"{variable}={wanted}: this provider is not installed")
            excluded.update(c for c in candidates if c != wanted)
        elif len(candidates) > 1:
            raise StartupError(
                f"Several providers of {capability} are installed ({', '.join(candidates)}); "
                f"choose one with {variable}"
            )
    return [m for m in modules if m.id not in excluded]


def _check_required(modules: list[Manifest]) -> None:
    present = {capability for m in modules for capability in m.provides}
    missing = sorted(contracts.REQUIRED_CAPABILITIES - present)
    if missing:
        raise StartupError(f"No provider installed for required capabilities: {missing}")


def _check_compatibility(modules: list[Manifest]) -> None:
    version = Version(contracts.CONTRACT_VERSION)
    for module in modules:
        if version not in SpecifierSet(module.api_compatibility):
            raise StartupError(
                f"Module {module.id} needs contract {module.api_compatibility}, "
                f"the kernel has {contracts.CONTRACT_VERSION}"
            )


def _in_dependency_order(modules: list[Manifest]) -> list[Manifest]:
    providers: dict[str, set[str]] = {}
    for module in modules:
        for capability in module.provides:
            providers.setdefault(capability, set()).add(module.id)
    graph: dict[str, list[str]] = {}
    for module in sorted(modules, key=lambda m: m.id):
        missing = [r for r in module.requires if r not in providers]
        if missing:
            raise StartupError(f"Module {module.id} requires missing capabilities: {missing}")
        needed = {
            provider
            for capability in [*module.requires, *module.optional]
            for provider in providers.get(capability, set())
        }
        graph[module.id] = sorted(needed - {module.id})
    try:
        order = list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise StartupError(f"Module dependency cycle: {exc.args[1]}") from exc
    by_id = {m.id: m for m in modules}
    return [by_id[module_id] for module_id in order]

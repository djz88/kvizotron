"""Typed ports of active modules. Filled once, from AppConfig.ready()."""

from django.conf import settings

from app.contracts import PORTS
from app.kernel.errors import StartupError


class UnknownPort(LookupError):
    pass


class ModuleDisabled(LookupError):
    pass


_ports: dict[tuple[str, str], tuple[object, str]] = {}


def register(capability: str, key: str, impl: object, owner: str) -> None:
    contract = PORTS.get(capability)
    if contract is None:
        raise StartupError(f"Module {owner}: unknown capability {capability}")
    module = next((m for m in settings.KVZ_MODULES if m.id == owner), None)
    if module is None:
        raise StartupError(f"Module {owner} is not active, cannot register {capability}")
    if capability not in module.provides:
        raise StartupError(f"Module {owner}: {capability} is missing from provides")
    if not isinstance(impl, contract):
        raise StartupError(f"Module {owner}: {key} does not satisfy the {capability} contract")
    if (capability, key) in _ports:
        taken_by = _ports[(capability, key)][1]
        raise StartupError(f"{capability}: {key} is registered twice, by {taken_by} and {owner}")
    _ports[(capability, key)] = (impl, owner)


def is_enabled(module_id: str) -> bool:
    """Read from the database each time, so a change applies at once. No row means enabled."""
    from app.kernel.models import PluginInstallation

    state = PluginInstallation.objects.filter(pk=module_id).values_list("enabled", flat=True)
    return next(iter(state), True)


def get(capability: str, key: str, *, include_disabled: bool = False) -> object:
    """Return a port. include_disabled serves re-evaluation of already stored revisions."""
    try:
        impl, owner = _ports[(capability, key)]
    except KeyError:
        raise UnknownPort(f"{capability}: {key}") from None
    if not include_disabled and not is_enabled(owner):
        raise ModuleDisabled(f"{capability}: {key}, module {owner} is disabled")
    return impl


def keys(capability: str) -> list[str]:
    ports = _ports.items()
    return sorted(k for (c, k), (_, owner) in ports if c == capability and is_enabled(owner))


def owner_of(capability: str, key: str) -> str:
    try:
        return _ports[(capability, key)][1]
    except KeyError:
        raise UnknownPort(f"{capability}: {key}") from None


def owned_by(module_id: str) -> set[tuple[str, str]]:
    return {port for port, (_, owner) in _ports.items() if owner == module_id}

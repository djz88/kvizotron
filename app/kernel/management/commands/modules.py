from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.kernel import lifecycle, registry
from app.kernel.errors import StartupError


class Command(BaseCommand):
    help = "List modules, enable or disable a plugin, or run the startup verification."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "enable", "disable", "verify"])
        parser.add_argument("module", nargs="?", help="module id, for enable and disable")

    def handle(self, *args, action, module, **options):
        if action == "list":
            self._list()
        elif action == "verify":
            self._verify()
        else:
            self._toggle(module, action == "enable")

    def _list(self):
        for manifest in settings.KVZ_MODULES:
            state = "enabled" if registry.is_enabled(manifest.id) else "disabled"
            self.stdout.write(f"{manifest.id}\t{manifest.kind}\t{manifest.version}\t{state}")

    def _verify(self):
        try:
            lifecycle.verify_startup()
        except StartupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write("OK")

    def _toggle(self, module, enabled):
        if not module:
            raise CommandError("A module id is required")
        try:
            lifecycle.set_enabled(module, enabled, actor_type="cli", actor_id=None)
        except lifecycle.LifecycleError as exc:
            raise CommandError(str(exc)) from exc

"""A module that needs a setting, without waiting for a real one to be installed."""

from django.conf import settings as django_settings
from django.test import override_settings

from app.kernel.manifest import SettingRequirement

REASON = "Needs the answers at the end."


def requiring(module_id="question.choice", **requirements):
    """Adds requirements to an installed module, as `key=(refuse, use)`."""
    wanted = {
        key: SettingRequirement(refuse=list(refuse), use=use, reason=REASON)
        for key, (refuse, use) in requirements.items()
    }
    modules = [
        module.model_copy(update={"settings_requirements": module.settings_requirements | wanted})
        if module.id == module_id
        else module
        for module in django_settings.KVZ_MODULES
    ]
    return override_settings(KVZ_MODULES=modules)


def needs_reveal_at_end(module_id="question.choice"):
    return requiring(module_id, reveal_moment=(["after_each"], "at_end"))

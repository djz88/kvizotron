from django.apps import AppConfig


class ParticipantsConfig(AppConfig):
    name = "app.plugins.participants"
    label = "participants"

    def ready(self):
        from app.kernel import registry

        from .policy import BasicParticipantPolicy

        plugin = BasicParticipantPolicy()
        registry.register("participant_policy", plugin.id, plugin, "participants.basic")

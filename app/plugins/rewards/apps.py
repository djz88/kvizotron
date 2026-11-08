from django.apps import AppConfig


class RewardsConfig(AppConfig):
    name = "app.plugins.rewards"
    label = "rewards"

    def ready(self):
        from app.kernel import registry

        from .thresholds import ThresholdReward

        plugin = ThresholdReward()
        registry.register("reward", plugin.id, plugin, "rewards.threshold")

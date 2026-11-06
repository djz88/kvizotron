from django.apps import AppConfig


class ScoringBasicConfig(AppConfig):
    name = "app.plugins.scoring"
    label = "scoring_basic"

    def ready(self):
        from app.kernel import registry

        from .strategies import AllOrNothing

        registry.register("scoring_strategy", AllOrNothing.id, AllOrNothing(), "scoring.basic")

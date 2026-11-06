from django.apps import AppConfig


class DemoConfig(AppConfig):
    name = "kvz_demo_question"

    def ready(self):
        from app.kernel import registry

        from .question import DemoExactScoring, DemoNumberQuestion

        owner = "question.demo"
        registry.register("question_type", "demo.number", DemoNumberQuestion(), owner)
        registry.register("scoring_strategy", "demo.exact", DemoExactScoring(), owner)

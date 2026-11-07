from app.plugins.quiz_flow.plugin import BasicFlow
from tests.contracts.quiz_flow import QuizFlowContract


class TestBasicFlow(QuizFlowContract):
    plugin = BasicFlow()

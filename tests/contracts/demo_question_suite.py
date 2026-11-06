"""Run by test_demo_question.py with the demo module installed; not collected on its own."""

from kvz_demo_question.question import DemoExactScoring, DemoNumberQuestion

from tests.contracts.question_type import QuestionTypeContract
from tests.contracts.scoring_strategy import ScoringStrategyContract

DEFINITION = {"prompt": "2 + 5 = ?", "answer": 7654321}


class TestDemoQuestion(QuestionTypeContract):
    plugin = DemoNumberQuestion()
    definition = DEFINITION
    answer_key_values = ["7654321"]
    valid_answer = {"value": 3}
    malformed_answers = [{}, {"value": "x"}, {"value": True}, "3", None]
    admin_form = {"prompt": ["2 + 5 = ?"], "answer": ["7"]}


class TestDemoScoring(ScoringStrategyContract):
    plugin = DemoExactScoring()
    definition = DEFINITION
    correct_answer = {"value": 7654321}
    wrong_answer = {"value": 3}

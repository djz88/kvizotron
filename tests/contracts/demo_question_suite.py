"""Run by test_demo_question.py with the demo module installed; not collected on its own."""

from kvz_demo_question.question import DemoExactScoring, DemoNumberQuestion

from tests.contracts.question_type import HOSTILE, QuestionTypeContract
from tests.contracts.scoring_strategy import ScoringStrategyContract

DEFINITION = {"prompt": "2 + 5 = ?", "answer": 7654321}


class TestDemoQuestion(QuestionTypeContract):
    plugin = DemoNumberQuestion()
    definition = DEFINITION
    answer_key_values = ["7654321"]
    valid_answer = {"value": 3}
    correct_answer = {"value": 7654321}
    malformed_answers = [{}, {"value": "x"}, {"value": True}, "3", None]
    admin_form = {"prompt": ["2 + 5 = ?"], "answer": ["7"]}
    changed_definitions = [{**DEFINITION, "prompt": "3 + 5 = ?"}, {**DEFINITION, "answer": 8}]
    answer_marker = 'value="3"'
    solution_marker = "7654321"
    hostile_definition = {"prompt": HOSTILE, "answer": 7654321}
    csv_bad_cells = [{"prompt": "x", "answer": "not a number"}]


class TestDemoScoring(ScoringStrategyContract):
    plugin = DemoExactScoring()

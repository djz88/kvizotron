"""Builds quizzes through the same services the admin screens use."""

from app.domain import authoring
from app.domain.models import Quiz, QuizRun

OPTION_A = "aaaa1111"
OPTION_B = "bbbb2222"
ADMIN_ID = "00000000-0000-7000-8000-000000000001"


def make_quiz(slug="kviz", locales=("cs",), **fields) -> Quiz:
    return Quiz.objects.create(
        slug=slug,
        title={locale: f"Název {locale}" for locale in locales},
        default_locale=locales[0],
        supported_locales=list(locales),
        **fields,
    )


def definition(locales, correct=OPTION_A, prompt="Otázka"):
    return {
        "prompt": {locale: f"{prompt} {locale}" for locale in locales},
        "options": [
            {"id": OPTION_A, "text": {locale: f"Ano {locale}" for locale in locales}},
            {"id": OPTION_B, "text": {locale: f"Ne {locale}" for locale in locales}},
        ],
        "correct": correct,
    }


def add_question(quiz, correct=OPTION_A, prompt="Otázka", question_id=None) -> str:
    config = definition(quiz.supported_locales, correct, prompt)
    return authoring.save_question(quiz, question_id, "choice.single", config)


def published_quiz(slug="kviz", locales=("cs",), questions=1, correct=OPTION_A, **fields) -> Quiz:
    quiz = make_quiz(slug, locales, **fields)
    for _ in range(questions):
        add_question(quiz, correct)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return quiz


def open_quiz_run(slug="kviz", locales=("cs",), questions=1, correct=OPTION_A, **fields) -> QuizRun:
    quiz = published_quiz(slug, locales, questions, correct, **fields)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)

"""Builds quizzes through the same services the admin screens use."""

from app.domain import authoring, banks
from app.domain.models import Quiz, QuizRun

OPTION_A = "aaaa1111"
OPTION_B = "bbbb2222"
ADMIN_ID = "00000000-0000-7000-8000-000000000001"


def make_quiz(slug="kviz", locales=("cs",), **fields) -> Quiz:
    fields.setdefault("description", {locale: f"Popis {locale}" for locale in locales})
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
        "correct": [correct],
    }


def add_question(quiz, correct=OPTION_A, prompt="Otázka", question_id=None) -> str:
    config = definition(quiz.supported_locales, correct, prompt)
    return authoring.save_question(quiz, question_id, "choice", config)


def published_quiz(slug="kviz", locales=("cs",), questions=1, correct=OPTION_A, **fields) -> Quiz:
    quiz = make_quiz(slug, locales, **fields)
    for _ in range(questions):
        add_question(quiz, correct)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return quiz


def open_quiz_run(slug="kviz", locales=("cs",), questions=1, correct=OPTION_A, **fields) -> QuizRun:
    quiz = published_quiz(slug, locales, questions, correct, **fields)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def make_bank(name="Dějepis"):
    return banks.create(name, admin_id=ADMIN_ID)


def add_bank_question(bank, locales=("cs",), tags=(), prompt="Otázka", **fields) -> str:
    return banks.save_question(
        bank,
        None,
        "choice",
        definition(locales, prompt=prompt),
        locales=("cs", "en", "uk"),
        tags=tags,
        **fields,
    )


def bank_with(count, name="Dějepis", locales=("cs",), tags=()):
    bank = make_bank(name)
    for number in range(count):
        add_bank_question(bank, locales, tags, prompt=f"Banka {number}")
    return bank


def add_row(
    quiz, bank, count=1, points=1, tag="", position=None, folder_id="", difficulty=""
) -> str:
    return authoring.save_draw(
        quiz,
        None,
        bank_id=str(bank.id),
        tag=tag,
        folder_id=folder_id,
        difficulty=difficulty,
        count=count,
        points=points,
        position=len(authoring.editable_questions(quiz)) if position is None else position,
    )


def keep(run: QuizRun, key: str, value: str) -> None:
    """Changes what the run kept (ADR-0069); a quiz change no longer reaches an opened run."""
    run.flow_json = run.flow_json | {key: value}
    run.save(update_fields=["flow_json"])

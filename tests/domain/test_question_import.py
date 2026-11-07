"""What an import file means: rows into a plan, a plan into a quiz, a draft or a bank (AC-13)."""

from pathlib import Path

import pytest

from app.contracts import CsvRow, ImageAddressInvalid, ParsedFile
from app.domain import authoring, banks, question_import, settings
from app.domain.models import QuestionBank, Quiz, QuizRevision
from app.domain.question_import import Target
from app.kernel.models import AuditEvent
from app.providers.csv_io.reader import parse_csv
from tests.domain.helpers import ADMIN_ID, add_question, make_bank, make_quiz, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
FIXTURE = Path(__file__).parents[1] / "fixtures" / "import" / "quiz-with-category.csv"
NEW = Target("new_quiz", None, None)
QUIZ_ROW = {
    "row_type": "quiz",
    "locales": "cs,en",
    "default_locale": "cs",
    "title_cs": "Kvíz",
    "title_en": "Quiz",
    "description_cs": "Popis",
    "description_en": "Description",
}
GOOD = {
    "type": "choice",
    "prompt_cs": "Otázka",
    "prompt_en": "Question",
    "option_1_cs": "A",
    "option_1_en": "A",
    "option_2_cs": "B",
    "option_2_en": "B",
    "correct": "A",
}


ALTS = {"image_alt_cs": "x", "image_alt_en": "x"}


def check_address(url):
    if not url.startswith("https://"):
        raise ImageAddressInvalid("Only https addresses work.")


def parsed(rows, files=frozenset()):
    columns = list(dict.fromkeys(name for row in rows for name in row))
    return ParsedFile(
        columns,
        [
            CsvRow(number + 2, {column: row.get(column, "") for column in columns})
            for number, row in enumerate(rows)
        ],
        frozenset(files),
    )


def plan_of(rows, target=NEW, mapping=None, files=frozenset(), check=check_address):
    return question_import.interpret(parsed(rows, files), target, mapping or {}, check)


def errors(plan):
    return [issue for issue in plan.issues if issue.is_error]


def warnings(plan):
    return [issue for issue in plan.issues if not issue.is_error]


def fixture_file():
    columns, rows = parse_csv(FIXTURE.read_bytes())
    return ParsedFile(columns, rows, frozenset())


def test_sample_with_category_plans_a_quiz_in_three_languages():
    file = fixture_file()
    assert set(question_import.unknown_columns(file.columns)) == {
        "category_cs",
        "category_en",
        "category_uk",
    }
    mapping = {"category_cs": "", "category_en": "", "category_uk": ""}
    plan = question_import.interpret(file, NEW, mapping, check_address)
    assert len(plan.questions) == 5
    assert plan.quiz.locales == ["cs", "en", "uk"]
    assert plan.quiz.title["uk"]
    assert "category_cs" in plan.unused_columns
    assert not errors(plan)
    assert not warnings(plan)
    first = plan.questions[0]
    assert first.explanation["en"]
    assert first.sources
    assert len(first.config["options"]) == 5


@pytest.mark.parametrize(
    ("cells", "column"),
    [
        ({"type": "nonsense"}, "type"),
        ({"type": ""}, "type"),
        ({"scoring": "nonsense"}, "scoring"),
        ({"prompt_cs": "", "prompt_en": ""}, None),
        ({"correct": "Z"}, "correct"),
        ({"points": "0"}, "points"),
        ({"points": "1.5"}, "points"),
        ({"points": "-1"}, "points"),
        ({"setting_show_sources": "nonsense"}, "setting_show_sources"),
        ({"setting_navigation_mode": "all_at_once"}, "setting_navigation_mode"),
        ({"image": "http://example.test/a.png"}, "image"),
        ({"image": "missing.png"}, "image"),
        ({"row_type": "nonsense"}, "row_type"),
        ({"sources": "\n".join(str(n) for n in range(11))}, "sources"),
        ({"sources": "x" * 301}, "sources"),
    ],
)
def test_row_error_names_row_and_column_and_skips_row(cells, column):
    plan = plan_of([QUIZ_ROW, GOOD | cells])
    assert not plan.questions
    assert [(issue.row, issue.column) for issue in errors(plan)] == [(3, column)]


def test_row_with_too_many_cells_is_an_error():
    file = parsed([QUIZ_ROW, GOOD])
    bad = CsvRow(3, file.rows[1].cells, "Too many cells.")
    file = ParsedFile(file.columns, [file.rows[0], bad], frozenset())
    plan = question_import.interpret(file, NEW, {}, check_address)
    assert not plan.questions
    assert errors(plan)[0].message == "Too many cells."


def test_good_and_bad_rows_keep_good_ones():
    plan = plan_of([QUIZ_ROW, GOOD, GOOD | {"correct": "Z"}, GOOD | {"prompt_cs": "Třetí"}])
    assert [question.row for question in plan.questions] == [3, 5]
    assert [issue.row for issue in errors(plan)] == [4]


def test_missing_translation_no_correct_answer_and_no_alt_are_warnings():
    plan = plan_of(
        [
            QUIZ_ROW,
            GOOD | {"prompt_en": ""},
            GOOD | {"correct": ""},
            GOOD | {"image": "https://example.test/a.png"},
        ]
    )
    assert len(plan.questions) == 3
    assert not errors(plan)
    assert {issue.row for issue in warnings(plan)} == {3, 4, 5}


def test_text_in_a_language_the_target_lacks_is_dropped_and_reported():
    quiz = make_quiz(locales=("cs",))
    target = Target("draft", quiz, None)
    plan = plan_of([{"type": "choice", "prompt_cs": "Q", "prompt_en": "Q en"}], target)
    assert list(plan.questions[0].config["prompt"]) == ["cs"]
    assert any("en" in issue.message for issue in warnings(plan))


def test_address_and_file_are_told_apart():
    plan = plan_of(
        [
            QUIZ_ROW,
            GOOD
            | {"image": "https://example.test/a.png", "image_alt_cs": "x", "image_alt_en": "x"},
            GOOD | {"image": "a.png"} | ALTS,
        ],
        files={"a.png"},
    )
    assert not errors(plan)
    assert len(plan.questions) == 2


def test_file_name_that_looks_like_an_address_is_never_taken_from_the_zip():
    plan = plan_of([QUIZ_ROW, GOOD | {"image": "ftp://x/a.png"}], files={"ftp://x/a.png"})
    assert errors(plan)


def test_image_cell_without_media_provider_is_a_row_error():
    plan = plan_of([QUIZ_ROW, GOOD | {"image": "https://example.test/a.png"}], check=None)
    assert [issue.column for issue in errors(plan)] == ["image"]


def test_unknown_schema_version_refuses_file():
    plan = plan_of([QUIZ_ROW | {"schema_version": "9"}, GOOD])
    assert plan.refused
    assert not plan.questions


def test_new_quiz_without_a_valid_quiz_row_refuses_file():
    assert plan_of([GOOD]).refused
    assert plan_of([QUIZ_ROW | {"title_cs": "", "title_en": ""}, GOOD]).refused
    assert plan_of([QUIZ_ROW | {"locales": "cs,xx"}, GOOD]).refused
    assert plan_of([QUIZ_ROW | {"default_locale": "uk"}, GOOD]).refused


def test_locales_default_to_those_with_a_title():
    plan = plan_of([QUIZ_ROW | {"locales": "", "default_locale": ""}, GOOD])
    assert plan.quiz.locales == ["cs", "en"]
    assert plan.quiz.default_locale == "cs"


def test_quiz_setting_outside_its_scope_or_values_is_an_error_and_is_dropped():
    plan = plan_of(
        [
            QUIZ_ROW
            | {
                "setting_navigation_mode": "step_back",
                "setting_shuffle_questions": "nonsense",
                "setting_allow_internal_image_addresses": "on",
            },
            GOOD,
        ]
    )
    assert plan.quiz.setting_values == {"navigation_mode": "step_back"}
    assert {issue.column for issue in errors(plan)} == {
        "setting_shuffle_questions",
        "setting_allow_internal_image_addresses",
    }


def test_quiz_row_into_draft_or_bank_is_ignored_with_warning():
    quiz = make_quiz(locales=("cs", "en"))
    for target in (Target("draft", quiz, None), Target("bank", None, make_bank())):
        plan = plan_of([QUIZ_ROW, GOOD], target)
        assert plan.quiz is None
        assert len(plan.questions) == 1
        assert any(issue.row == 2 for issue in warnings(plan))


def test_second_quiz_row_is_an_error():
    plan = plan_of([QUIZ_ROW, QUIZ_ROW, GOOD])
    assert [issue.row for issue in errors(plan)] == [3]


def test_tags_into_quiz_and_points_into_bank_are_reported_as_unused():
    quiz = make_quiz(locales=("cs", "en"))
    assert "tags" in plan_of([GOOD | {"tags": "a"}], Target("draft", quiz, None)).unused_columns
    bank = Target("bank", None, make_bank())
    assert "points" in plan_of([GOOD | {"points": "2"}], bank).unused_columns


def test_mapping_renames_a_column_and_blank_means_do_not_use():
    rows = [QUIZ_ROW, {k.replace("prompt_cs", "otazka"): v for k, v in GOOD.items()} | {"x": "y"}]
    plan = plan_of(rows, mapping={"otazka": "prompt_cs", "x": ""})
    assert plan.questions[0].config["prompt"]["cs"] == "Otázka"
    assert plan.unused_columns == ["x"]


def test_unmapped_unknown_column_is_unused():
    plan = plan_of([QUIZ_ROW, GOOD | {"x": "y"}])
    assert plan.unused_columns == ["x"]


def test_no_usable_row_creates_nothing():
    plan = plan_of([QUIZ_ROW, GOOD | {"correct": "Z"}])
    outcome = question_import.apply(plan, NEW, admin_id=ADMIN_ID)
    assert outcome.quiz is None
    assert outcome.added == 0
    assert not Quiz.objects.exists()


def test_apply_new_quiz_sets_fields_and_settings_and_nothing_is_published():
    rows = [
        QUIZ_ROW | {"slug": "muj-kviz", "setting_navigation_mode": "step_back"},
        GOOD | {"points": "3", "scoring": "", "explanation_cs": "Proto", "sources": "a\nb"},
    ]
    outcome = question_import.apply(plan_of(rows), NEW, admin_id=ADMIN_ID)
    quiz = outcome.quiz
    assert quiz.slug == "muj-kviz"
    assert quiz.supported_locales == ["cs", "en"]
    assert quiz.description["en"] == "Description"
    assert settings.quiz_override(settings.NAVIGATION_MODE, quiz) == "step_back"
    assert outcome.added == 1
    assert authoring.latest_published(quiz) is None
    assert not quiz.revisions.exclude(status=QuizRevision.Status.DRAFT).exists()
    question = authoring.editable_questions(quiz)[0]
    assert question["settings"]["points"] == 3
    assert question["sources"] == ["a", "b"]
    assert question["explanation"]["cs"] == "Proto"


def test_question_setting_is_kept_with_points():
    rows = [QUIZ_ROW, GOOD | {"points": "2", "setting_show_sources": "on"}]
    quiz = question_import.apply(plan_of(rows), NEW, admin_id=ADMIN_ID).quiz
    assert authoring.editable_questions(quiz)[0]["settings"] == {"points": 2, "show_sources": "on"}


def test_slug_comes_from_the_title_when_absent_or_invalid():
    plan = plan_of([QUIZ_ROW | {"slug": "ne platný!"}, GOOD])
    assert question_import.apply(plan, NEW, admin_id=ADMIN_ID).quiz.slug == "kviz"


def test_taken_slug_gets_a_number_with_warning():
    make_quiz(slug="kviz")
    plan = plan_of([QUIZ_ROW | {"slug": "kviz"}, GOOD])
    outcome = question_import.apply(plan, NEW, admin_id=ADMIN_ID)
    assert outcome.quiz.slug == "kviz-2"
    assert any("kviz-2" in issue.message for issue in outcome.issues)


def test_apply_to_draft_adds_after_existing_questions():
    quiz = published_quiz(locales=("cs", "en"))
    add_question(quiz, prompt="Stávající")
    outcome = question_import.apply(
        plan_of([GOOD], Target("draft", quiz, None)), Target("draft", quiz, None), admin_id=ADMIN_ID
    )
    assert outcome.quiz == quiz
    prompts = [q["definition"]["prompt"]["cs"] for q in authoring.editable_questions(quiz)]
    assert prompts[-1] == "Otázka"
    assert len(prompts) == 3


def test_apply_to_archived_quiz_refused():
    quiz = published_quiz(locales=("cs", "en"))
    target = Target("draft", quiz, None)
    plan = plan_of([GOOD], target)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        question_import.apply(plan, target, admin_id=ADMIN_ID)


def test_apply_to_bank_sets_tags_and_incomplete_language_is_a_row_error():
    bank = make_bank()
    target = Target("bank", None, bank)
    plan = plan_of(
        [GOOD | {"tags": "Dějepis, EU"}, {"type": "choice", "prompt_cs": "Bez možností"}], target
    )
    outcome = question_import.apply(plan, target, admin_id=ADMIN_ID)
    assert outcome.bank == bank
    assert outcome.added == 1
    assert [issue.row for issue in outcome.issues if issue.is_error] == [3]
    assert sorted(bank.questions.get().tags) == sorted(banks.tags_of(bank))
    assert len(bank.questions.get().tags) == 2
    assert QuestionBank.objects.count() == 1


def test_html_in_a_cell_is_escaped_when_played():
    rows = [
        QUIZ_ROW,
        GOOD | {"prompt_cs": "<script>x</script>", "prompt_en": "<script>x</script>"},
    ]
    quiz = question_import.apply(plan_of(rows), NEW, admin_id=ADMIN_ID).quiz
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = FormClient().post(f"/r/{run.id}/start", {"lang": "cs"}).content.decode()
    assert "<script>x</script>" not in html


def test_audit_records_counts_never_content():
    rows = [QUIZ_ROW, GOOD | {"prompt_cs": "Tajná otázka"}, GOOD | {"correct": "Z"}]
    question_import.apply(plan_of(rows), NEW, admin_id=ADMIN_ID)
    event = AuditEvent.objects.get(action="import.applied")
    assert event.details_json["added"] == 1
    assert event.details_json["errors"] == 1
    assert "Tajná" not in str(event.details_json)


def test_apply_writes_the_draft_once(monkeypatch):
    saves = []
    original = QuizRevision.save

    def counted(self, *args, **kwargs):
        saves.append(self.pk)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(QuizRevision, "save", counted)
    plan = plan_of([QUIZ_ROW] + [GOOD | {"prompt_cs": f"Q{n}"} for n in range(20)])
    quiz = question_import.apply(plan, NEW, admin_id=ADMIN_ID).quiz
    assert len(saves) <= 2  # creating the draft, and writing the questions once
    prompts = [q["definition"]["prompt"]["cs"] for q in authoring.editable_questions(quiz)]
    assert prompts == [f"Q{n}" for n in range(20)]

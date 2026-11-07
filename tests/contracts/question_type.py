"""Shared contract suite: every question type must pass it (contracts.md, invariant 1)."""

import json

import pytest

from app.contracts import (
    AnswerCount,
    CsvRowError,
    DefinitionRow,
    ItemGrade,
    QuestionTypePlugin,
)
from app.domain import settings

HOSTILE = '"><script>x'


class QuestionTypeContract:
    plugin: QuestionTypePlugin
    definition: dict
    answer_key_values: list[str]
    malformed_answers: list
    valid_answer: dict
    correct_answer: dict
    admin_form: dict
    changed_definitions: list[dict]  # each differs in one field; together they cover all fields
    answer_marker: str  # what `render_public` contains when given `valid_answer`
    hostile_definition: dict  # admin-entered text in every field is `HOSTILE`
    solution_marker: str  # what `render_solution` of `definition` must contain
    csv_bad_cells: list[dict]  # each makes `from_csv` refuse
    locales = ["cs"]
    locale = "cs"

    def content(self, config):
        """What a person reads. Ids are generated on import, so they do not count."""
        rows = self.plugin.describe_definition(config, self.locales)
        return [(row.label, row.locale, row.value) for row in rows]

    def test_csv_round_trip_keeps_the_content(self):
        cells = self.plugin.to_csv(self.definition, self.locales)
        again = self.plugin.from_csv(cells, self.locales)
        assert self.content(again) == self.content(self.definition)

    def test_csv_columns_cover_what_to_csv_writes(self):
        cells = self.plugin.to_csv(self.definition, self.locales)
        assert set(cells) <= set(self.plugin.csv_columns(self.locales))

    def test_every_changed_definition_changes_the_csv(self):
        original = self.plugin.to_csv(self.definition, self.locales)
        for changed in self.changed_definitions:
            assert self.plugin.to_csv(changed, self.locales) != original

    def test_bad_cells_raise_csv_row_error(self):
        for cells in self.csv_bad_cells:
            with pytest.raises(CsvRowError):
                self.plugin.from_csv(cells, self.locales)

    def test_from_csv_is_valid_for_publication(self):
        cells = self.plugin.to_csv(self.definition, self.locales)
        self.plugin.validate_definition(self.plugin.from_csv(cells, self.locales), self.locale)

    def payload(self):
        return self.plugin.public_payload(self.definition, self.locale)

    def test_question_settings_are_known_and_can_be_set_on_a_question(self):
        for key in self.plugin.question_settings():
            assert "question" in settings.CATALOGUE[key].scopes, key

    def test_file_fields_are_answer_fields(self):
        assert all(isinstance(field, str) for field in self.plugin.file_fields(self.definition))

    def test_no_answer_never_needs_grading(self):
        assert self.plugin.needs_grading(self.definition, None) is False

    def test_summarize_counts_answers_most_frequent_first(self):
        rows = list(
            self.plugin.summarize(
                self.definition,
                [self.valid_answer, self.valid_answer, self.correct_answer],
                self.locale,
            )
        )
        assert all(isinstance(row, AnswerCount) for row in rows)
        assert [row.count for row in rows] == sorted((row.count for row in rows), reverse=True)
        assert len({row.key for row in rows}) == len(rows)
        assert all(isinstance(row.label, str) and row.count > 0 for row in rows)

    def test_summarize_ignores_no_answer(self):
        assert list(self.plugin.summarize(self.definition, [{}, {}], self.locale)) == []

    def test_label_is_readable_text(self):
        label = str(self.plugin.label())
        assert label.strip() and label != self.plugin.id

    def test_satisfies_protocol(self):
        assert isinstance(self.plugin, QuestionTypePlugin)

    def test_public_payload_has_no_answer_key(self):
        payload = json.dumps(self.plugin.public_payload(self.definition, self.locale))
        for value in self.answer_key_values:
            assert value not in payload

    def test_render_public_contains_no_answer_key(self):
        payload = self.plugin.public_payload(self.definition, self.locale)
        html = self.plugin.render_public(payload, self.locale)
        for value in self.answer_key_values:
            assert value not in html

    def test_accepts_valid_submission(self):
        self.plugin.validate_submission(self.definition, self.valid_answer)

    def test_rejects_malformed_submission(self):
        for answer in self.malformed_answers:
            try:
                self.plugin.validate_submission(self.definition, answer)
            except ValueError:
                continue
            raise AssertionError(f"accepted malformed answer: {answer!r}")

    def test_grade_of_a_valid_answer_counts_within_total(self):
        grade = self.plugin.grade(self.definition, self.valid_answer)
        assert isinstance(grade, ItemGrade)
        assert 0 <= grade.right <= grade.total
        assert grade.wrong >= 0

    def test_grade_of_the_correct_answer_is_complete(self):
        grade = self.plugin.grade(self.definition, self.correct_answer)
        assert grade.right == grade.total and grade.wrong == 0 and grade.total > 0

    def test_grade_ignores_a_client_supplied_score(self):
        forged = self.valid_answer | {"score": 999, "earned_points": 999, "correct": True}
        honest = self.plugin.grade(self.definition, self.valid_answer)
        assert self.plugin.grade(self.definition, forged) == honest

    def test_grade_is_repeatable(self):
        first = self.plugin.grade(self.definition, self.correct_answer)
        assert self.plugin.grade(self.definition, self.correct_answer) == first

    def test_admin_form_produces_valid_definition(self):
        config = self.plugin.parse_admin(self.admin_form, self.locales)
        for locale in self.locales:
            self.plugin.validate_definition(config, locale)

    def test_render_admin_returns_html(self):
        assert "<" in self.plugin.render_admin(self.definition, self.locales)

    def test_describe_returns_plain_rows(self):
        rows = self.plugin.describe_definition(self.definition, self.locales)
        assert rows and all(isinstance(row, DefinitionRow) for row in rows)
        assert all(isinstance(row.value, str) for row in rows)
        assert len({(row.key, row.locale) for row in rows}) == len(rows)

    def test_any_definition_change_changes_the_description(self):
        original = self.plugin.describe_definition(self.definition, self.locales)
        for changed in self.changed_definitions:
            assert self.plugin.describe_definition(changed, self.locales) != original

    def test_render_public_without_answer_marks_nothing(self):
        html = self.plugin.render_public({**self.payload(), "id": "q1"}, self.locale)
        assert self.answer_marker not in html

    def test_render_public_shows_given_answer(self):
        html = self.plugin.render_public(
            {**self.payload(), "id": "q1"}, self.locale, self.valid_answer
        )
        assert self.answer_marker in html

    def test_render_public_escapes_a_hostile_answer(self):
        hostile = dict.fromkeys(self.valid_answer, '"><script>x')
        html = self.plugin.render_public({**self.payload(), "id": "q1"}, self.locale, hostile)
        assert "<script>x" not in html

    def test_render_solution_marks_the_correct_answer(self):
        html = self.plugin.render_solution(self.definition, self.locale, self.correct_answer)
        assert self.solution_marker in html

    def test_render_solution_without_an_answer(self):
        html = self.plugin.render_solution(self.definition, self.locale, None)
        assert self.solution_marker in html

    def test_render_solution_escapes_admin_text(self):
        html = self.plugin.render_solution(self.hostile_definition, self.locale, None)
        assert "<script>x" not in html and "&lt;script&gt;x" in html

    def test_render_solution_escapes_a_hostile_answer(self):
        hostile = dict.fromkeys(self.valid_answer, HOSTILE)
        html = self.plugin.render_solution(self.definition, self.locale, hostile)
        assert "<script>x" not in html

    def test_render_public_escapes_admin_text(self):
        """The page marks this output as safe, so the plugin must have escaped it (TD-011)."""
        payload = self.plugin.public_payload(self.hostile_definition, self.locale)
        html = self.plugin.render_public({**payload, "id": "q1"}, self.locale)
        assert "<script>x" not in html and "&lt;script&gt;x" in html

    def test_render_admin_escapes_admin_text(self):
        html = self.plugin.render_admin(self.hostile_definition, self.locales)
        assert "<script>x" not in html and "&lt;script&gt;x" in html

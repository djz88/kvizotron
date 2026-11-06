"""Shared contract suite: every question type must pass it (contracts.md, invariant 1)."""

import json

from app.contracts import QuestionTypePlugin


class QuestionTypeContract:
    plugin: QuestionTypePlugin
    definition: dict
    answer_key_values: list[str]
    malformed_answers: list
    valid_answer: dict
    admin_form: dict
    locales = ["cs"]
    locale = "cs"

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

    def test_admin_form_produces_valid_definition(self):
        config = self.plugin.parse_admin(self.admin_form, self.locales)
        for locale in self.locales:
            self.plugin.validate_definition(config, locale)

    def test_render_admin_returns_html(self):
        assert "<" in self.plugin.render_admin(self.definition, self.locales)

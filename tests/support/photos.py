"""Quizzes with a photo question, and a participant who plays them through the pages."""

import io

from django.test import Client
from PIL import Image

from app.domain import attempts, authoring, settings
from app.domain.models import Attempt
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz
from tests.support.client import FormClient


def text(response):
    return response.content.decode()


def jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (30, 30), "green").save(buffer, "JPEG")
    return buffer.getvalue()


def upload(data=None, name="fotka.jpg"):
    buffer = io.BytesIO(jpeg() if data is None else data)
    buffer.name = name
    return buffer


def field(html, name):
    return html.split(f'name="{name}" value="')[1].split('"')[0]


def photo_config(locale="cs", right=2, total=10):
    return {"prompt": {locale: "Vyfoťte"}, "auto": {"right": right, "total": total}}


def add_photo(quiz):
    authoring.save_question(
        quiz, None, "image_answer", photo_config(), points=10, scoring="partial"
    )


def photo_quiz(*, plain=False, level=None, **quiz_fields):
    quiz = make_quiz(**quiz_fields)
    if plain:
        add_question(quiz)
    add_photo(quiz)
    if level:
        settings.set_override("photo_visibility", quiz, level, admin_id=ADMIN_ID)
    return quiz


def run_of(quiz):
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


class Player:
    def __init__(self, run):
        self.client = Client()
        self.html = text(FormClient().post(f"/r/{run.id}/start", {"lang": "cs"}))
        self.attempt = Attempt.objects.get(run=run, pk=self._id())
        self.questions = attempts.questions_of(self.attempt)

    def _id(self):
        return self.html.split("/a/")[1].split("/")[0]

    def has_photo(self):
        return any(question["type"] == "image_answer" for question in self.questions)

    def question(self, type_id):
        return next(q["id"] for q in self.questions if q["type"] == type_id)

    def form(self, **fields):
        return {
            "attempt_token": field(self.html, "attempt_token"),
            "submission_key": field(self.html, "submission_key"),
            "lang": "cs",
            **fields,
        }

    def submit(self, fields=None, **extra):
        form = self.form(**(fields or {}))
        return self.client.post(f"/a/{self.attempt.id}/submit", form, **extra)

    def plain(self, fields=None):
        """Without a file, as a page without the file field sends it."""
        return FormClient().post(f"/a/{self.attempt.id}/submit", self.form(**(fields or {})))

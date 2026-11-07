"""B1 over HTTP: a new revision during an open round, for those who switch and those who do not."""

import re

import pytest

from app.domain.models import Attempt, QuizRun
from app.kernel.models import AdminUser
from tests.support.client import FormClient

PASSWORD = "dlouhe-a-neobvykle-heslo"
HTMX = {"HX-Request": "true"}
pytestmark = pytest.mark.django_db


def hidden(html, name):
    return re.search(rf'name="{name}" value="([^"]*)"', html).group(1)


def question_form(prompt, correct):
    return {"prompt_cs": prompt, "option_0_cs": "A", "option_1_cs": "B", f"correct_{correct}": "on"}


def publish(admin, quiz_id):
    url = f"/admin/quizzes/{quiz_id}/publish"
    fields = {"snapshot_hash": hidden(admin.get(url).content.decode(), "snapshot_hash")}
    assert admin.post(url, fields).status_code == 302


class Participant:
    def __init__(self, run):
        self.client = FormClient()
        self.html = self.client.post(f"/r/{run.id}/start", {"lang": "cs"}, headers=HTMX)
        self.html = self.html.content.decode()

    @property
    def attempt_id(self):
        return re.search(r'action="/a/([^/"]+)/submit"', self.html).group(1)

    def fields(self):
        return {
            "attempt_token": hidden(self.html, "attempt_token"),
            "submission_key": hidden(self.html, "submission_key"),
            "lang": "cs",
        }

    def status(self):
        return self.client.get(f"/a/{self.attempt_id}/revision-status", headers=HTMX)

    def switch(self, answers):
        url = f"/a/{self.attempt_id}/switch"
        response = self.client.post(url, self.fields() | answers, headers=HTMX)
        assert response.status_code == 200
        self.html = response.content.decode()

    def submit(self, answers):
        url = f"/a/{self.attempt_id}/submit"
        response = self.client.post(url, self.fields() | answers, headers=HTMX)
        assert response.status_code == 200
        return Attempt.objects.get(pk=self.attempt_id)


def option(run_questions, index, position):
    return run_questions[index]["definition"]["options"][position]["id"]


def test_switch_flow_end_to_end():
    AdminUser.objects.create_admin("alice", PASSWORD)
    admin = FormClient()
    admin.post("/admin/login", {"login": "alice", "password": PASSWORD})
    policy = {"revision_switch_policy": "notify_switch"}
    assert admin.post("/admin/settings", policy).status_code == 302
    admin.post(
        "/admin/quizzes/new",
        {
            "slug": "kviz",
            "description_cs": "Popis",
            "supported_locales": ["cs"],
            "default_locale": "cs",
            "title_cs": "Kvíz",
        },
    )
    quiz_url = admin.get("/admin/quizzes").content.decode()
    quiz_id = re.search(r"/admin/quizzes/([0-9a-f-]{36})/edit", quiz_url).group(1)
    new_question = f"/admin/quizzes/{quiz_id}/questions/new?type=choice"
    assert admin.post(new_question, question_form("První", "0")).status_code == 302
    assert admin.post(new_question, question_form("Druhá", "0")).status_code == 302
    publish(admin, quiz_id)
    assert admin.post(f"/admin/quizzes/{quiz_id}/runs").status_code == 302
    run = QuizRun.objects.get()
    first_revision = run.current_revision_id
    questions = run.current_revision.snapshot_json["questions"]
    first, second = questions[0]["id"], questions[1]["id"]

    switching, staying = Participant(run), Participant(run)
    assert switching.status().status_code == 204

    # The correct option of the first question changes.
    edit = f"/admin/quizzes/{quiz_id}/questions/{first}/edit"
    changed = question_form("První", "1") | {
        "option_0_id": option(questions, 0, 0),
        "option_1_id": option(questions, 0, 1),
    }
    assert admin.post(edit, changed).status_code == 302
    publish(admin, quiz_id)
    run.refresh_from_db()
    assert run.current_revision_id != first_revision

    status = switching.status()
    assert status.status_code == 200 and "/switch" in status.content.decode()

    kept = option(questions, 1, 0)
    switching.switch({f"{first}:options[]": option(questions, 0, 0), f"{second}:options[]": kept})
    assert switching.html.count("checked") == 1 and f'value="{kept}" checked' in switching.html
    assert "question-changed" in switching.html
    result = switching.submit(
        {f"{first}:options[]": option(questions, 0, 1), f"{second}:options[]": kept}
    )
    assert result.revision_id == run.current_revision_id and result.score == 2

    old = staying.submit(
        {f"{first}:options[]": option(questions, 0, 0), f"{second}:options[]": kept}
    )
    assert old.revision_id == first_revision and old.score == 2

    newcomer = Attempt.objects.get(pk=Participant(run).attempt_id)
    assert newcomer.revision_id == run.current_revision_id

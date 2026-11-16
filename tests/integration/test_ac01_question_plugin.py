"""AC-01: a new question type, installed as a package, needs no change to the core."""

import json

from tests.support.run import DEMO_SITE, run_manage, run_python

PLAY = """
import json, re
from app.domain.models import Quiz, QuizRun
from app.kernel.models import AdminUser

client.force_login(AdminUser.objects.create_admin("alice", "dlouhe-a-neobvykle-heslo"))
new = client.post("/admin/quizzes/new", {
    "description_cs": "Popis",
    "slug": "demo", "supported_locales": ["cs"], "default_locale": "cs", "title_cs": "Demo",
})
quiz = Quiz.objects.get()
url = f"/admin/quizzes/{quiz.id}/questions/new?type=demo.number"
editor = client.get(url).content.decode()
saved = client.post(url, {"prompt": "2 + 5 = ?", "answer": "7"}).status_code
publish_url = f"/admin/quizzes/{quiz.id}/publish"
snapshot_hash = re.search(
    r'name="snapshot_hash" value="([^"]*)"', client.get(publish_url).content.decode()
).group(1)
published = client.post(publish_url, {"snapshot_hash": snapshot_hash}).status_code
opened = client.post(f"/admin/quizzes/{quiz.id}/runs").status_code
run = QuizRun.objects.get()
qid = run.current_revision.snapshot_json["questions"][0]["id"]

def play(value):
    html = client.post(f"/r/{run.id}/start", {"lang": "cs"}).content.decode()
    action = re.search(r'action="(/a/[^"?]+/submit)(?:[?][^"]*)?"', html).group(1)
    fields = {
        name: re.search(rf'name="{name}" value="([^"]*)"', html).group(1)
        for name in ("attempt_token", "submission_key")
    }
    result = client.post(action, fields | {f"{qid}:value": value})
    return html, result.status_code, result.content.decode()

html, right_status, right = play("7")
_, wrong_status, wrong = play("3")
print(json.dumps({
    "types": 'type=demo.number' in client.get(f"/admin/quizzes/{quiz.id}/edit").content.decode(),
    "editor": 'name="answer"' in editor,
    "saved": saved, "published": published, "opened": opened,
    "rendered": f'name="{qid}:value"' in html,
    "key_hidden": ">7<" not in html and 'value="7"' not in html,
    "right": [right_status, "1 / 1" in right],
    "wrong": [wrong_status, "0 / 1" in wrong],
}))
"""


def migrated(db, **kwargs):
    result = run_manage("migrate", "--noinput", db=db, **kwargs)
    assert result.returncode == 0, result.stderr


def test_demo_question_type_works_through_editor_rendering_and_scoring(tmp_path):
    db = tmp_path / "db.sqlite3"
    migrated(db, sites=[DEMO_SITE])
    result = run_python(PLAY, db=db, sites=[DEMO_SITE])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {
        "types": True,
        "editor": True,
        "saved": 302,
        "published": 302,
        "opened": 302,
        "rendered": True,
        "key_hidden": True,
        "right": [200, True],
        "wrong": [200, True],
    }


def test_startup_stops_when_open_run_needs_uninstalled_type(tmp_path):
    db = tmp_path / "db.sqlite3"
    migrated(db, sites=[DEMO_SITE])
    assert run_python(PLAY, db=db, sites=[DEMO_SITE]).returncode == 0
    code = "from app.kernel.lifecycle import verify_startup\nverify_startup()"
    result = run_python(code, db=db)
    assert result.returncode != 0
    assert "demo.number" in result.stderr

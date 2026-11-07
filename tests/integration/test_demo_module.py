import json

from tests.support.modules import make_module
from tests.support.run import DEMO_SITE, run_manage, run_python

PLAY = "/m/question.demo/play/"


def migrated(tmp_path, **kwargs):
    db = tmp_path / "db.sqlite3"
    result = run_manage("migrate", "--noinput", db=db, **kwargs)
    assert result.returncode == 0, result.stderr
    return db


def test_core_works_without_module(tmp_path):
    result = run_python(f"print(client.get('{PLAY}').status_code)", db=migrated(tmp_path))
    assert result.stdout.strip() == "404", result.stderr


def test_module_migrates_and_serves_route_through_jinja2(tmp_path):
    db = migrated(tmp_path, sites=[DEMO_SITE])
    code = f"r = client.get('{PLAY}'); print(r.status_code); print(r.content.decode())"
    result = run_python(code, db=db, sites=[DEMO_SITE])
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("200")
    assert "<h1>2 + 5 = ?</h1>" in result.stdout


def test_module_registers_ports(tmp_path):
    code = (
        "from app.kernel import registry\n"
        "print(registry.keys('question_type'), registry.keys('scoring_strategy'))"
    )
    result = run_python(code, db=migrated(tmp_path, sites=[DEMO_SITE]), sites=[DEMO_SITE])
    types = "['choice', 'demo.number', 'image_answer', 'matching', 'number', 'text']"
    assert result.stdout.strip() == f"{types} ['all_or_nothing', 'demo.exact', 'partial']", (
        result.stderr
    )


def test_client_score_is_ignored_and_answer_stored(tmp_path):
    db = migrated(tmp_path, sites=[DEMO_SITE])
    code = (
        "import json\n"
        "from kvz_demo_question.models import DemoAnswer\n"
        "body = json.dumps({'value': 3, 'score': 999})\n"
        "r = client.post('/m/question.demo/submit/', body, content_type='application/json')\n"
        "print(json.dumps([r.status_code, r.json(), DemoAnswer.objects.count()]))"
    )
    result = run_python(code, db=db, sites=[DEMO_SITE])
    assert json.loads(result.stdout) == [200, {"earned_points": 0.0}, 1], result.stderr


def test_malformed_submission_is_rejected(tmp_path):
    db = migrated(tmp_path, sites=[DEMO_SITE])
    code = (
        "r = client.post('/m/question.demo/submit/', '{\"value\": \"x\"}',"
        " content_type='application/json')\n"
        "print(r.status_code)"
    )
    result = run_python(code, db=db, sites=[DEMO_SITE])
    assert result.stdout.strip() == "400", result.stderr


def test_module_ships_complete_migrations(tmp_path):
    result = run_manage(
        "makemigrations", "--check", "--dry-run", db=tmp_path / "db.sqlite3", sites=[DEMO_SITE]
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_bad_app_path_aborts_naming_it(tmp_path):
    make_module(tmp_path, "bad.app", app="nope_missing.apps.X")
    result = run_manage("check", db=tmp_path / "db.sqlite3", sites=[tmp_path])
    assert result.returncode != 0
    assert "nope_missing" in result.stderr


def test_bad_port_in_ready_aborts_naming_module(tmp_path):
    apps_body = (
        "\n    def ready(self):\n"
        "        from app.kernel import registry\n"
        "        registry.register('question_type', 'x', object(), owner='bad.port')\n"
    )
    make_module(tmp_path, "bad.port", provides=["question_type"], apps_body=apps_body)
    result = run_manage("check", db=tmp_path / "db.sqlite3", sites=[tmp_path])
    assert result.returncode != 0
    assert "bad.port" in result.stderr


def test_broken_module_stops_startup_before_any_request(tmp_path):
    make_module(tmp_path, "bad.import", source="import does_not_exist_anywhere\n")
    result = run_manage("check", db=tmp_path / "db.sqlite3", sites=[tmp_path])
    assert result.returncode != 0
    assert "bad.import" in result.stderr


def test_disable_gives_404_without_restart_and_keeps_data(tmp_path):
    db = migrated(tmp_path, sites=[DEMO_SITE])
    code = (
        "from app.kernel import lifecycle\n"
        "from kvz_demo_question.models import DemoAnswer\n"
        "DemoAnswer.objects.create(earned_points=1.0)\n"
        "cli = {'actor_type': 'cli', 'actor_id': None}\n"
        f"before = client.get('{PLAY}').status_code\n"
        "lifecycle.set_enabled('question.demo', False, **cli)\n"
        f"off = client.get('{PLAY}').status_code\n"
        "kept = DemoAnswer.objects.count()\n"
        "lifecycle.set_enabled('question.demo', True, **cli)\n"
        f"on = client.get('{PLAY}').status_code\n"
        "print(before, off, kept, on)"
    )
    result = run_python(code, db=db, sites=[DEMO_SITE])
    assert result.stdout.strip() == "200 404 1 200", result.stderr


def test_other_routes_ignore_module_gate(tmp_path):
    db = migrated(tmp_path, sites=[DEMO_SITE])
    code = (
        "from app.kernel import lifecycle\n"
        "lifecycle.set_enabled('question.demo', False, actor_type='cli', actor_id=None)\n"
        "print(client.get('/healthz').status_code)"
    )
    result = run_python(code, db=db, sites=[DEMO_SITE])
    assert result.stdout.strip() == "200", result.stderr

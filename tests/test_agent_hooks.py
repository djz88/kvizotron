"""The hook that keeps agents from deleting Docker volumes (.claude/settings.json)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "guard_docker_volumes.py"


def decision(command: str) -> str | None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    done = subprocess.run(
        [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, check=True
    )
    if not done.stdout:
        return None
    return json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"]


@pytest.mark.parametrize(
    "command",
    [
        "docker compose -p kvizotron-browser down -v",
        "docker compose -p kvizotron-browser -f deploy/compose.yaml down --volumes",
        "docker compose --project-name=kvizotron-browser down --remove-orphans -v",
        "docker-compose -p kvizotron-browser down -v",
        "cd deploy && docker compose -p kvizotron-browser down -v && echo done",
        "bash -c 'docker compose -p kvizotron-browser down -v'",
        "COMPOSE_PROJECT_NAME=kvizotron-browser docker compose down -v",
        "docker volume rm kvizotron-browser_db",
        "docker volume rm kvizotron-tmp_db kvizotron-browser_media",
        "docker volume remove kvizotron-browser_db",
        "docker compose -p kvizotron-browser down -v;",
    ],
)
def test_deleting_the_browser_stack_data_is_refused(command):
    assert decision(command) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "docker compose down -v",
        "docker compose -f deploy/compose.yaml down -v",
        'docker compose -p "$PROJECT" down -v',
        "docker volume prune -f",
        "docker volume prune --all",
        "docker system prune -a --volumes",
        "mkdir -p x && docker compose down -v",
        "docker compose down -v;",
        "(docker compose down -v)",
        "docker compose down -v&& echo done",
        "docker compose down --volumes=true",
        "docker compose down \\\n  -v",
        "docker --context prod volume prune",
        "docker volume rm $(docker volume ls -q)",
        "docker volume ls -q | xargs docker volume rm",
        "docker volume remove $NAME",
    ],
)
def test_deleting_volumes_of_an_unnamed_stack_is_refused(command):
    assert decision(command) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "docker compose -p kvizotron-tmp down -v",
        "docker compose -p=kvizotron-ipcheck -f deploy/compose.yaml down --volumes",
        "COMPOSE_PROJECT_NAME=kvizotron-tmp docker compose down -v",
        "docker volume rm kvizotron-tmp_db",
        "docker volume remove kvizotron-tmp_db",
        "docker compose -p kvizotron-tmp down -v && echo done",
    ],
)
def test_deleting_volumes_of_another_named_stack_asks_the_person(command):
    assert decision(command) == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "docker compose -p kvizotron-browser up -d --build",
        "docker compose -p kvizotron-browser down",
        "docker compose -p kvizotron-browser logs -f app",
        "docker compose -p kvizotron-browser exec -T app python manage.py check",
        "docker volume ls",
        "docker system prune -f",
        "mkdir -p x && docker compose down",
        "docker compose -p kvizotron-tmp up -d && echo -v",
        "docker run -v data:/data alpine ls",
        "make smoke",
        "grep -rn volumes deploy/compose.yaml",
        "git log --oneline",
    ],
)
def test_other_commands_pass(command):
    assert decision(command) is None


def test_the_hook_is_registered_for_bash():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    entries = settings["hooks"]["PreToolUse"]
    commands = [
        hook["command"]
        for entry in entries
        if entry["matcher"] == "Bash"
        for hook in entry["hooks"]
    ]
    assert any(HOOK.name in command for command in commands)

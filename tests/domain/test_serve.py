"""ADR-0066: one container runs the migrations, the application and the jobs loop."""

import signal
import sys
import threading
import time

from app.domain.management.commands import serve

PY = sys.executable
CLEAN_STOP = "signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))"
SLEEPER = [PY, "-c", f"import signal,sys,time; {CLEAN_STOP}; time.sleep(60)"]
DEAF = [
    PY,
    "-c",
    "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
]


def started_commands(monkeypatch):
    """Records every child `run` starts, then starts it as usual."""
    started = []
    real = serve.subprocess.Popen

    def popen(command, *args, **kwargs):
        started.append(command)
        return real(command, *args, **kwargs)

    monkeypatch.setattr(serve.subprocess, "Popen", popen)
    return started


def test_a_failed_migration_starts_nothing(monkeypatch):
    started = started_commands(monkeypatch)
    migrate = [PY, "-c", "raise SystemExit(4)"]
    assert serve.run(migrate, [(SLEEPER, 1.0)]) == 4
    assert started == [migrate]  # the migration only


def test_a_child_that_ends_stops_the_others_with_its_code():
    """The container ends, so its orchestrator restarts all of it, never half of it."""
    stop = threading.Event()
    begun = time.monotonic()
    code = serve.run(None, [(SLEEPER, 5.0), ([PY, "-c", "raise SystemExit(3)"], 5.0)], stop=stop)
    assert code == 3
    assert time.monotonic() - begun < 10


def test_a_child_that_ends_cleanly_still_ends_the_container_with_failure():
    code = serve.run(None, [(SLEEPER, 5.0), ([PY, "-c", "pass"], 5.0)], stop=threading.Event())
    assert code == 1


def test_a_stop_passes_sigterm_and_waits_for_a_clean_end(tmp_path, monkeypatch):
    """Each child gets SIGTERM, ends by itself (it writes a mark), and none is left running."""
    processes = []
    real = serve.subprocess.Popen

    def popen(command, *args, **kwargs):
        processes.append(real(command, *args, **kwargs))
        return processes[-1]

    monkeypatch.setattr(serve.subprocess, "Popen", popen)
    marks = [tmp_path / "a", tmp_path / "b"]
    children = [
        (
            [
                PY,
                "-c",
                "import pathlib,signal,sys,time\n"
                f"def stop(*a): pathlib.Path({str(mark)!r}).write_text('ok'); sys.exit(0)\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "pathlib.Path(sys.argv[1]).write_text('up')\n"
                "time.sleep(60)",
                str(mark) + ".up",
            ],
            5.0,
        )
        for mark in marks
    ]
    stop = threading.Event()

    def when_up():
        while not all((tmp_path / f"{m.name}.up").exists() for m in marks):
            time.sleep(0.05)
        stop.set()

    threading.Thread(target=when_up, daemon=True).start()
    assert serve.run(None, children, stop=stop) == 0
    assert all(mark.read_text() == "ok" for mark in marks)
    assert all(process.poll() is not None for process in processes)


def test_a_child_that_ignores_the_stop_is_killed_after_its_grace():
    stop = threading.Event()
    threading.Timer(0.5, stop.set).start()
    begun = time.monotonic()
    assert serve.run(None, [(DEAF, 1.0)], stop=stop) == 0
    assert time.monotonic() - begun < 5


def test_the_children_are_the_application_and_the_jobs_loop():
    commands = [command for command, _grace in serve.children()]
    assert commands[0][: len(serve.IMAGE_COMMAND)] == serve.IMAGE_COMMAND
    assert "--workers" in commands[0] and commands[0][commands[0].index("--workers") + 1] == "1"
    assert commands[1][-1] == "jobs"
    assert [grace for _command, grace in serve.children()] == [30.0, 115.0]


def test_the_image_has_a_single_container_target_and_compose_keeps_the_default():
    """`docker build --target single` runs `serve`; the last stage, which Compose builds, stays."""
    import json
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()
    stages = re.findall(r"^FROM (\S+)(?: AS (\w+))?$", text, re.M)
    assert [name for _image, name in stages] == ["app", "single", ""]
    assert stages[-1][0] == "app"  # the default build is the image Compose runs
    commands = [json.loads(found) for found in re.findall(r"^CMD (\[.*\])$", text, re.M)]
    assert commands == [serve.IMAGE_COMMAND, ["python", "manage.py", "serve"]]


def test_every_child_gets_its_grace_from_one_moment():
    """AC-183: The stop window is the longest grace, not their sum (the pod gives 120 s in all)."""
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    begun = time.monotonic()
    serve.run(None, [(DEAF, 1.0), (DEAF, 1.5)], stop=stop)
    assert time.monotonic() - begun < 2.5


def test_a_stop_during_the_migration_starts_nothing(monkeypatch):
    started = started_commands(monkeypatch)
    stop = threading.Event()
    migrate = [PY, "-c", "import time; time.sleep(0.5)"]
    threading.Timer(0.1, stop.set).start()
    assert serve.run(migrate, [(SLEEPER, 1.0)], stop=stop) == 0
    assert started == [migrate]  # the migration only


def test_a_child_killed_by_a_signal_ends_the_container_like_a_shell_would():
    code = serve.run(
        None,
        [([PY, "-c", "import os,signal; os.kill(os.getpid(), signal.SIGKILL)"], 1.0)],
        stop=threading.Event(),
    )
    assert code == 128 + signal.SIGKILL


def test_a_child_that_cannot_start_stops_the_ones_already_running():
    import pytest

    stop = threading.Event()
    begun = time.monotonic()
    with pytest.raises(OSError):
        serve.run(None, [(SLEEPER, 5.0), (["/no/such/program"], 5.0)], stop=stop)
    assert time.monotonic() - begun < 5


def test_the_database_directory_is_made_before_the_migration(tmp_path, monkeypatch):
    """A fresh Kubernetes volume is empty: the image's /data/db does not show through it."""
    database = tmp_path / "db" / "kvizotron.sqlite3"
    monkeypatch.setenv("KVZ_DB_PATH", str(database))
    serve.prepare()
    assert database.parent.is_dir()


def test_gunicorn_keeps_idle_connections_longer_than_an_ingress():
    """An ingress reuses idle upstream connections for 60 s; gunicorn's 2 s would reset POSTs."""
    keep = serve.GUNICORN[serve.GUNICORN.index("--keep-alive") + 1]
    assert int(keep) > 60


def test_the_command_prepares_migrates_and_exits_with_the_code_of_run(monkeypatch, tmp_path):
    database = tmp_path / "db" / "x.sqlite3"
    monkeypatch.setenv("KVZ_DB_PATH", str(database))
    seen = {}

    def fake_run(migrate, commands, *, stop):
        seen["migrate"] = migrate
        seen["handler"] = signal.getsignal(signal.SIGTERM)
        return 7

    monkeypatch.setattr(serve, "run", fake_run)
    before = signal.getsignal(signal.SIGTERM)
    try:
        import pytest

        with pytest.raises(SystemExit) as ended:
            serve.Command().handle()
    finally:
        signal.signal(signal.SIGTERM, before)
        signal.signal(signal.SIGINT, signal.default_int_handler)
    assert ended.value.code == 7
    assert database.parent.is_dir()
    assert seen["migrate"][-2:] == ["migrate", "--noinput"]
    assert callable(seen["handler"]) and seen["handler"] is not before

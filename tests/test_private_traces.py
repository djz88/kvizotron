"""tools/private_traces.py stops a commit or a push carrying local traces (CLAUDE.md, Rules)."""

import os
import subprocess
import sys
from pathlib import Path

from tools import private_traces

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "private_traces.py"
# Built at run time: written whole, this file would trip its own hook.
HOME, USERS, SCRATCH = "/" + "home/", "/" + "Users/", "/tmp/" + "claude-"  # noqa: S108
SESSION, SESSION_LINE = "claude.ai/code/" + "session_", "Claude-" + "Session:"


def run(cwd, *args, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True, env=env
    )


def git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)  # noqa: S607
    return done.stdout.strip()


def repo(tmp_path, words=""):
    tmp_path.mkdir(exist_ok=True)
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / ".git" / "info").mkdir(exist_ok=True)
    (tmp_path / ".git" / "info" / "private-traces").write_text(words, encoding="utf-8")
    return tmp_path


def test_general_traces_are_found_without_a_list():
    text = f"see {HOME}alice/x, {USERS}bob, {SCRATCH}1000/a, {SESSION}01\n{SESSION_LINE} x"
    found = private_traces.traces(text, private_traces.pattern([]))
    assert found == sorted([f"{USERS}bob", f"{HOME}alice", f"{SCRATCH}1000", SESSION_LINE, SESSION])


def test_placeholders_and_example_addresses_pass():
    text = "<repo>/docs, <scratchpad>/x, https://192.168.1.10:8443/admin, /home is a word"
    assert private_traces.traces(text, private_traces.pattern(["10.9.8."])) == []


def test_the_private_list_ignores_case_and_comments(tmp_path):
    path = tmp_path / "private-traces"
    path.write_text("# mine\nalice99  # name\n10.9.8.\n")
    words = private_traces.private_words(path)
    assert words == ["alice99", "10.9.8."]
    assert private_traces.traces("ALICE99 at 10.9.8.7", private_traces.pattern(words)) == [
        "10.9.8.",
        "ALICE99",
    ]


def test_a_missing_list_is_empty(tmp_path):
    assert private_traces.private_words(tmp_path / "private-traces") == []


def test_a_staged_file_with_a_trace_is_refused(tmp_path):
    repo(tmp_path, "alice99\n")
    (tmp_path / "plan.md").write_text(f"run from {HOME}alice99/kvizotron\n")
    (tmp_path / "ok.md").write_text("run from <repo>\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\0alice99")
    refused = run(tmp_path, "files", "plan.md", "ok.md", "logo.png")
    assert refused.returncode == 1
    assert f"plan.md: {HOME}alice99" in refused.stderr
    assert "ok.md" not in refused.stderr and "logo.png" not in refused.stderr
    assert run(tmp_path, "files", "ok.md").returncode == 0


def test_a_commit_message_with_a_session_line_is_refused(tmp_path):
    message = tmp_path / "MSG"
    message.write_text(f"fix: x\n\nCo-Authored-By: A <a@example.com>\n{SESSION_LINE} https://x\n")
    assert run(tmp_path, "message", str(message)).returncode == 1
    message.write_text(
        f"fix: x\n\nCo-Authored-By: A <a@example.com>\n# {SESSION_LINE} in a comment\n"
    )
    assert run(tmp_path, "message", str(message)).returncode == 0


def test_a_push_checks_only_the_new_commits(tmp_path):
    repo(tmp_path, "alice99\n")
    (tmp_path / "a.md").write_text("alice99 was here\n")
    git(tmp_path, "add", "a.md")
    git(tmp_path, "commit", "-qm", "old")
    old = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "b.md").write_text("clean\n")
    git(tmp_path, "add", "b.md")
    git(tmp_path, "commit", "-qm", "new")
    env = {**os.environ, "PRE_COMMIT_FROM_REF": old, "PRE_COMMIT_TO_REF": "HEAD"}
    assert run(tmp_path, "push", env=env).returncode == 0
    (tmp_path / "c.md").write_text(f"from {HOME}alice99\n")
    git(tmp_path, "add", "c.md")
    git(tmp_path, "commit", "-qm", "leak")
    pushed = run(tmp_path, "push", env=env)
    assert pushed.returncode == 1
    assert f"{HOME}alice99" in pushed.stderr


def test_the_hooks_are_installed_for_commit_message_and_push():
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "default_install_hook_types: [pre-commit, commit-msg, pre-push]" in config
    for hook in ("private-traces", "private-traces-message", "private-traces-push"):
        assert f"id: {hook}\n" in config


def test_the_repository_itself_holds_no_traces():
    tracked = git(ROOT, "ls-files").split()
    found = private_traces.check_files(
        [str(ROOT / name) for name in tracked], private_traces.GENERAL
    )
    assert found == []


def test_a_worktree_uses_the_list_of_the_main_checkout(tmp_path):
    main = repo(tmp_path / "main", "alice99\n")
    (main / "a.md").write_text("x\n")
    git(main, "add", "a.md")
    git(main, "commit", "-qm", "first")
    git(main, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "wt")
    (tmp_path / "wt" / "b.md").write_text("by alice99\n")
    assert run(tmp_path / "wt", "list").stdout == "private-traces: ok (1 words)\n"
    assert run(tmp_path / "wt", "files", "b.md").returncode == 1


def test_a_missing_list_is_reported_but_does_not_stop_a_commit(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "ok.md").write_text("clean\n")
    listed = run(tmp_path, "list")
    assert listed.returncode == 1
    assert "make private-traces" in listed.stderr
    committed = run(tmp_path, "files", "ok.md")
    assert committed.returncode == 0
    assert "make private-traces" in committed.stderr


def test_make_creates_an_empty_list_and_keeps_an_existing_one(tmp_path):
    git(tmp_path, "init", "-q")
    make = ["make", "-s", "-f", str(ROOT / "Makefile"), "private-traces"]
    created = subprocess.run(make, cwd=tmp_path, capture_output=True, text=True)  # noqa: S607
    path = tmp_path / ".git" / "info" / "private-traces"
    assert created.returncode == 0
    assert path.is_file()
    assert private_traces.private_words(path) == []
    path.write_text("alice99\n")
    kept = subprocess.run(make, cwd=tmp_path, capture_output=True, text=True)  # noqa: S607
    assert "already exists" in kept.stdout
    assert path.read_text() == "alice99\n"


ALLOWING = (
    "alice99\n"
    "# the owner may be named where GitHub and readers look for them\n"
    "allow alice99@example.org SECURITY.md .github/CODEOWNERS  # contact\n"
    "allow @alice99\n"
)


def test_allow_lines_are_exceptions_not_words(tmp_path):
    path = tmp_path / "private-traces"
    path.write_text(ALLOWING)
    assert private_traces.private_words(path) == ["alice99"]
    assert private_traces.allowances(path) == [
        private_traces.Allow("alice99@example.org", ("SECURITY.md", ".github/CODEOWNERS")),
        private_traces.Allow("@alice99", ()),
    ]


def test_an_allowed_text_hides_only_the_hits_inside_it():
    found = private_traces.pattern(["alice99"])
    text = "write to ALICE99@example.org, ask @alice99, not alice99 alone"
    allowed = ["alice99@example.org", "@alice99"]
    assert private_traces.traces(text, found, allowed) == ["alice99"]
    assert private_traces.traces("only ALICE99@example.org", found, allowed) == []


def test_an_allowance_holds_in_its_files_or_everywhere(tmp_path):
    repo(tmp_path, ALLOWING)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text("* @alice99 alice99@example.org\n")
    (tmp_path / "SECURITY.md").write_text("Write to alice99@example.org.\n")
    (tmp_path / "docs.md").write_text("Owner: @alice99\n")
    (tmp_path / "plan.md").write_text("Write to alice99@example.org.\n")
    allowed = run(tmp_path, "files", "SECURITY.md", ".github/CODEOWNERS", "docs.md")
    assert allowed.returncode == 0, allowed.stderr
    refused = run(tmp_path, "files", "plan.md")
    assert refused.returncode == 1
    assert "plan.md: alice99" in refused.stderr
    (tmp_path / "SECURITY.md").write_text("Ask alice99 directly.\n")
    assert run(tmp_path, "files", "SECURITY.md").returncode == 1
    absolute = run(tmp_path, "files", str(tmp_path / ".github" / "CODEOWNERS"))
    assert absolute.returncode == 0, absolute.stderr


def test_a_push_honours_the_allowances_per_file(tmp_path):
    repo(tmp_path, ALLOWING)
    (tmp_path / "a.md").write_text("clean\n")
    git(tmp_path, "add", "a.md")
    git(tmp_path, "commit", "-qm", "old")
    old = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "SECURITY.md").write_text("Write to alice99@example.org.\n")
    git(tmp_path, "add", "SECURITY.md")
    git(tmp_path, "commit", "-qm", "contact for @alice99")
    env = {**os.environ, "PRE_COMMIT_FROM_REF": old, "PRE_COMMIT_TO_REF": "HEAD"}
    assert run(tmp_path, "push", env=env).returncode == 0
    (tmp_path / "b.md").write_text("Write to alice99@example.org.\n")
    git(tmp_path, "add", "b.md")
    git(tmp_path, "commit", "-qm", "leak")
    pushed = run(tmp_path, "push", env=env)
    assert pushed.returncode == 1
    assert ": alice99" in pushed.stderr


def test_a_commit_message_takes_only_the_allowances_for_everywhere(tmp_path):
    repo(tmp_path, ALLOWING)
    message = tmp_path / "MSG"
    message.write_text("docs: thanks @alice99\n")
    assert run(tmp_path, "message", str(message)).returncode == 0
    message.write_text("docs: write to alice99@example.org\n")
    assert run(tmp_path, "message", str(message)).returncode == 1


def test_a_bare_allow_line_is_neither_a_word_nor_an_exception(tmp_path):
    path = tmp_path / "private-traces"
    path.write_text("alice99\nallow\nallow\t # forgot the text\n")
    assert private_traces.private_words(path) == ["alice99"]
    assert private_traces.allowances(path) == []


def test_an_allowance_names_one_exact_path(tmp_path):
    repo(tmp_path, ALLOWING)
    (tmp_path / "docs").mkdir()
    (tmp_path / "SECURITY.md").write_text("Write to alice99@example.org.\n")
    (tmp_path / "docs" / "SECURITY.md").write_text("Write to alice99@example.org.\n")
    assert run(tmp_path, "files", "./SECURITY.md").returncode == 0
    other = run(tmp_path, "files", "docs/SECURITY.md")
    assert other.returncode == 1
    assert "docs/SECURITY.md: alice99" in other.stderr


def test_a_push_reads_file_names_only_outside_the_changed_lines(tmp_path):
    repo(tmp_path, ALLOWING)
    (tmp_path / "a.md").write_text("clean\n")
    git(tmp_path, "add", "a.md")
    git(tmp_path, "commit", "-qm", "old")
    old = git(tmp_path, "rev-parse", "HEAD")
    # An added line "++ …" shows in the diff as "+++ …", like a file header.
    (tmp_path / "SECURITY.md").write_text("++ contact\nWrite to alice99@example.org.\n")
    git(tmp_path, "add", "SECURITY.md")
    git(tmp_path, "commit", "-qm", "contact")
    env = {**os.environ, "PRE_COMMIT_FROM_REF": old, "PRE_COMMIT_TO_REF": "HEAD"}
    pushed = run(tmp_path, "push", env=env)
    assert pushed.returncode == 0, pushed.stderr

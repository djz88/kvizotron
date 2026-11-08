#!/usr/bin/env python3
"""Stop an agent's command that would delete Docker volumes.

The data of the kvizotron-browser stack stays (the owner uses it), so deleting it is refused, and so
is deleting volumes when the command does not say whose they are. Another named stack is the
person's call: CLAUDE.md lets data-deleting commands run only with their consent.

It reads the text of the command, so it guards against a slip, not against intent: an alias, a
script or a variable holding the whole command gets past it. It may also stop a command that only
mentions such a deletion, for example in a commit message. `make smoke` is not affected, because the
script's own commands are not seen here.
"""

import json
import re
import sys

KEPT = "kvizotron-browser"
BETWEEN_COMMANDS = re.compile(r"[;&|\n()`]")
QUOTES = re.compile(r"['\"]")
LITERAL = re.compile(r"[\w.-]+")
VOLUMES_FLAG = re.compile(r"(?:-[a-zA-Z]*v[a-zA-Z]*|--volumes)(?:=.*)?")
PROJECT_ASSIGNMENT = re.compile(r"(?:-p|--project-name|COMPOSE_PROJECT_NAME)=(.*)")
UNNAMED = (
    "Příkaz maže svazky a neříká jednoznačně, kterého stacku, takže by mohl zasáhnout "
    f"{KEPT}. Pojmenuj stack přes -p, nebo ať to člověk spustí sám."
)
KEPT_DATA = f"Data stacku {KEPT} se nemažou. Na nové ověření stačí nový kvíz."
CONSENT = "Příkaz maže svazky Dockeru. Mazání dat potvrzuje člověk."


def simple_commands(command: str) -> list[list[str]]:
    joined = command.replace("\\\n", " ")
    return [QUOTES.sub(" ", part).split() for part in BETWEEN_COMMANDS.split(joined)]


def docker_arguments(words: list[str]) -> tuple[bool, list[str]] | None:
    """Whether it is the compose command, and the words after it; None when not Docker."""
    if "docker-compose" in words:
        return True, words[words.index("docker-compose") + 1 :]
    if "docker" in words:
        rest = words[words.index("docker") + 1 :]
        return "compose" in rest, rest
    return None


def names_a_project(words: list[str]) -> bool:
    for index, word in enumerate(words):
        assigned = PROJECT_ASSIGNMENT.fullmatch(word)
        if assigned:
            value = assigned[1]
        elif word in ("-p", "--project-name") and index + 1 < len(words):
            value = words[index + 1]
        else:
            continue
        if LITERAL.fullmatch(value):
            return True
    return False


def after(words: list[str], *names: str) -> list[str] | None:
    """The words after `names`, which follow each other, or None when they do not appear."""
    for index in range(len(words)):
        if tuple(words[index : index + len(names)]) == names:
            return words[index + len(names) :]
    return None


def deletion(words: list[str]) -> str | None:
    """The answer for one simple command: `UNNAMED`, `CONSENT`, or None when it deletes nothing."""
    parsed = docker_arguments(words)
    if parsed is None:
        return None
    compose, rest = parsed
    if compose:
        flags = after(rest, "down")
        if flags is None or not any(VOLUMES_FLAG.fullmatch(flag) for flag in flags):
            return None
        return CONSENT if names_a_project(words) else UNNAMED
    if after(rest, "volume", "prune") is not None:
        return UNNAMED
    pruned = after(rest, "system", "prune")
    if pruned is not None:
        return UNNAMED if any(flag.startswith("--volumes") for flag in pruned) else None
    removed = after(rest, "volume", "rm")
    if removed is None:
        removed = after(rest, "volume", "remove")
    if removed is None:
        return None
    names = [word for word in removed if not word.startswith("-")]
    return CONSENT if names and all(LITERAL.fullmatch(name) for name in names) else UNNAMED


def verdict(command: str) -> tuple[str, str] | None:
    answers = {deletion(words) for words in simple_commands(command)} - {None}
    if not answers:
        return None
    if KEPT in command:
        return "deny", KEPT_DATA
    return ("deny", UNNAMED) if UNNAMED in answers else ("ask", CONSENT)


def main() -> None:
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    result = verdict(command)
    if result:
        decision, reason = result
        output = {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
        print(json.dumps({"hookSpecificOutput": output}, ensure_ascii=False))


if __name__ == "__main__":
    main()

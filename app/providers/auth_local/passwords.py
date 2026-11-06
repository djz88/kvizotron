"""Reads a new password for a CLI command. Never as an argument: those show in `ps` and history."""

from getpass import getpass
from typing import Any, TextIO

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError


def read_password(options: dict[str, Any], stdin: TextIO, *, user: Any = None) -> str:
    password = stdin.readline().removesuffix("\n") if options["password_stdin"] else _ask(stdin)
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise CommandError(" ".join(exc.messages)) from exc
    return password


def _ask(stdin: TextIO) -> str:
    if not stdin.isatty():
        raise CommandError("No terminal to ask for the password; use --password-stdin")
    try:
        password = getpass("Password: ")
        again = getpass("Password again: ")
    except (EOFError, KeyboardInterrupt) as exc:
        raise CommandError("Cancelled") from exc
    if password != again:
        raise CommandError("Passwords do not match")
    return password

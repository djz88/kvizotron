import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app.kernel import audit
from app.providers.auth_local.passwords import read_password

REFUSED = "An admin already exists; use reset_admin_password for a lost password"


class Command(BaseCommand):
    help = "Create the first admin. Refused once any admin exists."
    stealth_options = ("stdin",)

    def add_arguments(self, parser):
        parser.add_argument("login")
        parser.add_argument(
            "--password-stdin", action="store_true", help="read the password from standard input"
        )

    def handle(self, *args, login, **options):
        users = get_user_model().objects
        if users.exists():  # before asking for a password that could not be used
            raise CommandError(REFUSED)
        password = read_password(options, options.get("stdin", sys.stdin))
        with transaction.atomic():  # IMMEDIATE: a parallel run waits here and sees this admin
            if users.exists():
                raise CommandError(REFUSED)
            try:
                user = users.create_admin(login, password)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            audit.record(
                actor_type="cli",
                actor_id=None,
                action="admin.created",
                entity_type="admin",
                entity_id=str(user.pk),
            )
        self.stdout.write(f"Admin {login} created")

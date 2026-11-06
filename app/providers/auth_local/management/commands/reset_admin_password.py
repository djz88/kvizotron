import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app.kernel import audit
from app.providers.auth_local.passwords import read_password


class Command(BaseCommand):
    help = "Set a new password for an admin. This also ends the admin's sessions."
    stealth_options = ("stdin",)

    def add_arguments(self, parser):
        parser.add_argument("login")
        parser.add_argument(
            "--password-stdin", action="store_true", help="read the password from standard input"
        )

    def handle(self, *args, login, **options):
        user = get_user_model().objects.filter(login=login).first()
        if user is None:
            raise CommandError(f"Admin {login} does not exist")
        password = read_password(options, options.get("stdin", sys.stdin), user=user)
        user.set_password(password)  # sessions are bound to the password hash (ADR-0036)
        with transaction.atomic():
            user.save(update_fields=["password"])
            audit.record(
                actor_type="cli",
                actor_id=None,
                action="admin.password_reset",
                entity_type="admin",
                entity_id=str(user.pk),
            )
        self.stdout.write(f"Password of admin {login} changed")

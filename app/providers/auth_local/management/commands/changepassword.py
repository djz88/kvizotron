from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Not available; use reset_admin_password."

    def add_arguments(self, parser):
        parser.add_argument("username", nargs="?")

    def handle(self, *args, **options):
        raise CommandError("Use reset_admin_password: it revokes sessions and audits the reset")

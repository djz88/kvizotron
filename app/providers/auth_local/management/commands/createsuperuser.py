from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Not available; use init_admin."

    def handle(self, *args, **options):
        raise CommandError("Use init_admin for the first admin; further admins are added in /admin")

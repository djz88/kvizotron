from django.core.management.base import BaseCommand

from app.domain import retention


class Command(BaseCommand):
    help = "Delete the data of runs whose period has ended, and photo files nothing refers to."

    def handle(self, *args, **options):
        self.stdout.write(f"Runs deleted: {retention.run_pass()}")

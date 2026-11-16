from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from app.domain import backup


class Command(BaseCommand):
    help = (
        "Restore a verified backup (YYYY-MM-DD or latest) over the database and the media. "
        "Stop the app and jobs services first; the replaced data is kept in pre-restore-<time>."
    )

    # The system checks open a connection to the live database that stays open and would be taken
    # for another user of it: the restore refuses while any connection holds the database.
    requires_system_checks: list[str] = []

    def add_arguments(self, parser):
        parser.add_argument("backup", help="the date of the backup (YYYY-MM-DD) or latest")

    def handle(self, *args, **options):
        try:
            directory = backup.resolve(options["backup"])
            report = backup.restore(directory, timezone.now())
        except backup.BackupError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(
            f"Restored the backup of {directory.name}: a database of {report.database_bytes}"
            f" bytes and {report.media_files} media files. The previous data is in"
            f" {report.previous.name}."
        )
        if report.warning:
            self.stderr.write(self.style.WARNING(report.warning))

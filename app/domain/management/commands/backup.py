from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from app.domain import backup


class Command(BaseCommand):
    help = "Make one verified backup of the database and the media, then delete old ones."

    def handle(self, *args, **options):
        now = timezone.now()
        try:
            directory = backup.create(now)
            self.stdout.write(f"Backup made: {directory} ({backup.file_count(directory)} files)")
            pruned = backup.prune(now, settings.KVZ_BACKUP_RETENTION_DAYS)
        except backup.BackupError as exc:
            raise CommandError(str(exc)) from None
        if pruned.stayed:  # the backup stands; the exit code says the cleanup did not finish
            self.stderr.write(f"{len(pruned.stayed)} old backup directories could not be deleted")
            raise CommandError("The backup was made, but old backups stayed")

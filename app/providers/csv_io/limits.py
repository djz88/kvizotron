"""Limits of an import. Constants, like ADR-0028: they guard the server."""

from datetime import timedelta

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 500
MAX_ZIP_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_IMAGE_BYTES = 16 * 1024 * 1024  # the media provider then applies its own limits
JOB_LIFETIME = timedelta(hours=24)

# Results export (D2): a link lives a day; the worker runs few jobs at once.
EXPORT_LIFETIME = timedelta(hours=24)
EXPORT_SLOTS_TOTAL = 2
EXPORT_SLOTS_PER_ADMIN = 1

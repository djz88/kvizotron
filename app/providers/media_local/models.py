from uuid import uuid7

from django.db import models


class MediaAsset(models.Model):
    """A stored file. Alternative texts belong to the question that shows the image."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    kind = models.CharField(max_length=20, default="image")
    storage_key = models.CharField(max_length=100, unique=True)
    mime_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    private = models.BooleanField(default=False)  # a participant's photo, never on `/media/`

    class Meta:
        db_table = "media_asset"


class AddressCheck(models.Model):
    """The last check of an address some quiz loads an image from. Holds no image."""

    address = models.CharField(max_length=2000, unique=True)
    ok = models.BooleanField()
    checked_at = models.DateTimeField()

    class Meta:
        db_table = "media_address_check"

"""Shared contract suite: every media storage module must pass it (the parts retention needs)."""

import io
from datetime import timedelta

from django.utils import timezone
from PIL import Image

from app.contracts import MediaStorageProvider

MISSING = "00000000-0000-7000-8000-000000000001"


def picture() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 30, 30)).save(buffer, "PNG")
    return buffer.getvalue()


class MediaStorageSuite:
    def __init__(self, provider: object) -> None:
        assert isinstance(provider, MediaStorageProvider)
        self.provider: MediaStorageProvider = provider

    def run(self) -> None:
        self.delete_image_removes_the_asset()
        self.delete_image_of_an_id_that_is_not_there_is_harmless()
        self.private_assets_older_than_lists_only_private_assets_before_the_cutoff()
        self.a_deleted_private_asset_is_no_longer_listed()

    def delete_image_removes_the_asset(self) -> None:
        asset_id = self.provider.store_participant_image(picture(), run_assets=[])
        assert self.provider.exists(asset_id)
        assert self.provider.load(asset_id) is not None
        self.provider.delete_image(asset_id)
        assert not self.provider.exists(asset_id)
        assert self.provider.load(asset_id) is None
        self.provider.delete_image(asset_id)  # a repeat finds nothing and says nothing

    def delete_image_of_an_id_that_is_not_there_is_harmless(self) -> None:
        kept = self.provider.store_image(picture())
        self.provider.delete_image(MISSING)
        self.provider.delete_image("nonsense")
        assert self.provider.exists(kept)
        self.provider.delete_image(kept)

    def private_assets_older_than_lists_only_private_assets_before_the_cutoff(self) -> None:
        private = self.provider.store_participant_image(picture(), run_assets=[])
        public = self.provider.store_image(picture())
        try:
            after = timezone.now() + timedelta(minutes=5)
            found = self.provider.private_assets_older_than(after)
            assert private in found
            assert public not in found
            assert all(isinstance(asset_id, str) for asset_id in found)
            before = timezone.now() - timedelta(hours=1)
            assert private not in self.provider.private_assets_older_than(before)
        finally:
            self.provider.delete_image(private)
            self.provider.delete_image(public)

    def a_deleted_private_asset_is_no_longer_listed(self) -> None:
        private = self.provider.store_participant_image(picture(), run_assets=[])
        self.provider.delete_image(private)
        after = timezone.now() + timedelta(minutes=5)
        assert private not in self.provider.private_assets_older_than(after)

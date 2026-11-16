"""The media storage provider through its contract."""

import pytest

from app.kernel import registry
from tests.contracts.media_storage import MediaStorageSuite

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)


def test_local_media_passes_the_suite():
    MediaStorageSuite(registry.get("media_storage", "local")).run()
